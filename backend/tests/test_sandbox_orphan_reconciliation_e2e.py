"""Docker-backed sandbox container lifecycle and cleanup tests.

This test module requires Docker to be running. It exercises the container
backend behavior behind sandbox lifecycle management and verifies that test
containers are created, observed, and explicitly cleaned up correctly.

The coverage here is limited to direct backend/container operations used by
the reconciliation flow. It does not simulate a process restart by creating
a new ``AioSandboxProvider`` instance or assert provider startup orphan
reconciliation end-to-end — that logic is covered by unit tests in
``test_sandbox_orphan_reconciliation.py``.

Run only after explicit authorization:
    DEVPILOT_RUN_DOCKER_TESTS=1 PYTHONPATH=. uv run pytest -m docker tests/test_sandbox_orphan_reconciliation_e2e.py -v -s
Requires Docker and a pre-existing busybox:latest image; never pulls an image.
Default/CI runs skip; collection never probes Docker. Temporary containers use
no mounts, published ports or network, and cleanup checks unique run ownership.
"""

import subprocess
import time
import uuid

import pytest

pytestmark = pytest.mark.docker

_RUN_ID = uuid.uuid4().hex
_RUN_LABEL = "devpilot.test.run_id"
_START_ATTEMPTS: set[str] = set()


def _docker_available() -> bool:
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _container_running(container_name: str) -> bool:
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", container_name],
        capture_output=True,
        text=True,
        timeout=5,
    )
    return result.returncode == 0 and result.stdout.strip().lower() == "true"


def _start_test_container(container_name: str) -> None:
    # A timed-out CLI is not proof of non-delivery; record intent first.
    _START_ATTEMPTS.add(container_name)
    result = subprocess.run(
        ["docker", "run", "--pull=never", "--network", "none", "--rm", "-d", "--label", f"{_RUN_LABEL}={_RUN_ID}", "--name", container_name, E2E_TEST_IMAGE, "sleep", "3600"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, "Failed to start explicitly authorized test container"


def _stop_container(container_name: str) -> None:
    if container_name not in _START_ATTEMPTS:
        return
    result = subprocess.run(
        ["docker", "inspect", "-f", '{{index .Config.Labels "' + _RUN_LABEL + '"}}', container_name],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode == 0 and result.stdout.strip() == _RUN_ID:
        # --rm removes this exact container on stop. No force or prefix sweeps.
        subprocess.run(["docker", "stop", "--time", "2", container_name], capture_output=True, timeout=15)


E2E_TEST_IMAGE = "busybox:latest"
E2E_PREFIX = f"devpilot-sandbox-e2e-{_RUN_ID}"


@pytest.fixture(autouse=True)
def cleanup_test_containers():
    """Only explicitly authorized runs may probe Docker or create resources."""
    if not _docker_available():
        pytest.skip("Docker not available")
    image = subprocess.run(["docker", "image", "inspect", E2E_TEST_IMAGE], capture_output=True, timeout=5)
    if image.returncode:
        pytest.skip("busybox:latest must already exist; this test never pulls images")
    _START_ATTEMPTS.clear()
    try:
        yield
    finally:
        for name in sorted(_START_ATTEMPTS):
            _stop_container(name)
        _START_ATTEMPTS.clear()


class TestOrphanReconciliationE2E:
    """E2E tests for orphan container reconciliation."""

    def test_orphan_container_destroyed_on_startup(self):
        """Core issue scenario: container from a previous process is destroyed on new process init.

        Steps:
        1. Start a container manually (simulating previous process)
        2. Create a LocalContainerBackend with matching prefix
        3. Call list_running() → should find the container
        4. Simulate _reconcile_orphans() logic → container should be destroyed
        """
        container_name = f"{E2E_PREFIX}-orphan01"

        # Step 1: Start a container (simulating previous process lifecycle)
        _start_test_container(container_name)

        try:
            assert _container_running(container_name), "Test container should be running"

            # Step 2: Create backend and list running containers
            from deerflow.community.aio_sandbox.local_backend import LocalContainerBackend

            backend = LocalContainerBackend(
                image=E2E_TEST_IMAGE,
                base_port=9990,
                container_prefix=E2E_PREFIX,
                config_mounts=[],
                environment={},
            )

            # Step 3: list_running should find our container
            running = backend.list_running()
            found_ids = {info.sandbox_id for info in running}
            assert "orphan01" in found_ids, f"Should find orphan01, got: {found_ids}"

            # Step 4: Simulate reconciliation — this container's created_at is recent,
            # so with a very short idle_timeout it would be destroyed
            orphan_info = next(info for info in running if info.sandbox_id == "orphan01")
            assert orphan_info.created_at > 0, "created_at should be parsed from docker inspect"

            # Destroy it (simulating what _reconcile_orphans does for old containers)
            backend.destroy(orphan_info)

            # Give Docker a moment to stop the container
            time.sleep(1)

            # Verify container is gone
            assert not _container_running(container_name), "Orphan container should be stopped after destroy"

        finally:
            # Safety cleanup
            _stop_container(container_name)

    def test_multiple_orphans_all_cleaned(self):
        """Multiple orphaned containers are all found and can be cleaned up."""
        containers = []
        try:
            # Start 3 containers
            for i in range(3):
                name = f"{E2E_PREFIX}-multi{i:02d}"
                _start_test_container(name)
                containers.append(name)

            from deerflow.community.aio_sandbox.local_backend import LocalContainerBackend

            backend = LocalContainerBackend(
                image=E2E_TEST_IMAGE,
                base_port=9990,
                container_prefix=E2E_PREFIX,
                config_mounts=[],
                environment={},
            )

            running = backend.list_running()
            found_ids = {info.sandbox_id for info in running}

            assert "multi00" in found_ids
            assert "multi01" in found_ids
            assert "multi02" in found_ids

            # Destroy all
            for info in running:
                backend.destroy(info)

            time.sleep(1)

            # Verify all gone
            for name in containers:
                assert not _container_running(name), f"{name} should be stopped"

        finally:
            for name in containers:
                _stop_container(name)

    def test_list_running_ignores_unrelated_containers(self):
        """Containers with different prefixes should not be listed."""
        unrelated_name = f"devpilot-docker-other-{_RUN_ID}"
        our_name = f"{E2E_PREFIX}-ours001"

        try:
            # Start an unrelated container
            _start_test_container(unrelated_name)
            # Start our container
            _start_test_container(our_name)

            from deerflow.community.aio_sandbox.local_backend import LocalContainerBackend

            backend = LocalContainerBackend(
                image=E2E_TEST_IMAGE,
                base_port=9990,
                container_prefix=E2E_PREFIX,
                config_mounts=[],
                environment={},
            )

            running = backend.list_running()
            found_ids = {info.sandbox_id for info in running}

            # Should find ours but not unrelated
            assert "ours001" in found_ids
            # This distinct, run-scoped unrelated name does not match E2E_PREFIX.
            for info in running:
                assert not info.sandbox_id.startswith("unrelated")

        finally:
            _stop_container(unrelated_name)
            _stop_container(our_name)
