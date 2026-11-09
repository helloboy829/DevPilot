import { expect, it } from "@rstest/core";

import {
  buildTaskCreate,
  taskActorsValid,
  taskCanPass,
  taskCaseMatches,
  taskIdValid,
  taskLeaseActive,
  taskPhaseAllowed,
  taskReceiptMatches,
} from "@/core/evaluation/task-policy";

import {
  activeTask,
  actors,
  caseData,
  id,
  ownerTask,
  task,
  taskCase,
} from "../../../fixtures/review-task";

it("requires canonical exact task IDs and three distinct UUIDs", () => {
  expect(taskIdValid(id)).toBe(true);
  for (const value of [
    id.toUpperCase(),
    id + "/case",
    " " + id,
    "../" + id,
    "",
  ])
    expect(taskIdValid(value)).toBe(false);
  expect(taskActorsValid(actors)).toBe(true);
  for (const values of [
    [actors[0], actors[0], actors[2]],
    [actors[0], actors[1]],
    ["not-an-account", actors[1], actors[2]],
    [actors[0].replace("1", "A"), actors[1], actors[2]],
  ])
    expect(taskActorsValid(values)).toBe(false);
});
it("builds only frozen identity plus explicit narrow share consent", () => {
  const payload = buildTaskCreate(caseData, actors);
  expect(payload).toEqual({
    run_id: "r1",
    ordinal: 1,
    case_hash: "b".repeat(64),
    reviewer_ids: actors.slice(0, 2),
    arbitrator_id: actors[2],
    share_reference: true,
    confirmed: true,
  });
  expect(JSON.stringify(payload)).not.toContain("SYNTHETIC_GOLD");
  expect(() =>
    buildTaskCreate(caseData, [actors[0], actors[0], actors[2]]),
  ).toThrow();
});
it("reconciles only the same owner task, case, project and exact three assignees", () => {
  const receipt = {
    id,
    projectId: "p1",
    payload: buildTaskCreate(caseData, actors),
  };
  expect(taskReceiptMatches(ownerTask(), receipt)).toBe(true);
  for (const mismatch of [
    ownerTask({ id: "e".repeat(32) }),
    ownerTask({ project_id: "p2" }),
    ownerTask({ run_id: "r2" }),
    ownerTask({ case_hash: "e".repeat(64) }),
    task(),
    ownerTask({ assignments: [] }),
  ])
    expect(taskReceiptMatches(mismatch, receipt)).toBeFalsy();
});
it("leases and review phases fail closed at exact expiry and arbitration gate", () => {
  expect(taskLeaseActive(activeTask(), Date.now())).toBe(true);
  expect(
    taskLeaseActive(
      activeTask({
        assignment: {
          role: "reviewer_1",
          status: "active",
          lease_until_ms: 100,
        },
      }),
      100,
    ),
  ).toBe(false);
  expect(taskLeaseActive(task())).toBe(false);
  expect(taskPhaseAllowed(ownerTask())).toBe(false);
  expect(taskPhaseAllowed(task({ role: "arbitrator" }))).toBe(false);
  expect(
    taskPhaseAllowed(task({ role: "arbitrator", status: "escalated" })),
  ).toBe(true);
  expect(taskPhaseAllowed(task({ status: "resolved" }))).toBe(false);
});
it("opened evidence is bound to the entire frozen task and current viewed revision", () => {
  const t = activeTask();
  expect(taskCaseMatches(taskCase(t), t)).toBe(true);
  for (const opened of [
    taskCase(t, { task_id: "e".repeat(32) }),
    taskCase(t, { task_revision: 1 }),
    taskCase(t, { round: 2 }),
    taskCase(t, { ordinal: 2 }),
    taskCase(t, { subject_hash: "e".repeat(64) }),
    taskCase(t, { case_hash: "e".repeat(64) }),
  ])
    expect(taskCaseMatches(opened, t)).toBe(false);
});
it("technical or missing evidence never allows PASS, while empty collected text is evidence", () => {
  expect(taskCanPass(taskCase())).toBe(true);
  expect(taskCanPass(taskCase(undefined, { output: "" }))).toBe(true);
  for (const value of [
    { output: null },
    { evidence_hash: null },
    { state: "delivery_unknown" },
    { technical: { ...caseData.technical, kind: "timeout" } },
  ])
    expect(taskCanPass(taskCase(undefined, value))).toBe(false);
});

it("rejects incomplete evidence and non-hex evidence hashes", () => {
  expect(taskCanPass(taskCase(undefined, { evidence_hash: "present" }))).toBe(
    false,
  );
  expect(taskCanPass(taskCase(undefined, { output: undefined }))).toBe(false);
  expect(taskCaseMatches(taskCase(), ownerTask())).toBe(false);
});
