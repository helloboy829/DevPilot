"""Configuration for the custom agents management API."""

from pydantic import BaseModel, Field


class AgentsApiConfig(BaseModel):
    """Configuration for custom-agent and user-profile management routes."""

    enabled: bool = Field(
        default=True,
        description=("Whether authenticated users may manage their own custom agents over HTTP (enabled by default). When disabled, the gateway rejects custom-agent and private USER.md management routes."),
    )


_agents_api_config: AgentsApiConfig = AgentsApiConfig()


def get_agents_api_config() -> AgentsApiConfig:
    """Get the current agents API configuration."""
    return _agents_api_config


def set_agents_api_config(config: AgentsApiConfig) -> None:
    """Set the agents API configuration."""
    global _agents_api_config
    _agents_api_config = config


def load_agents_api_config_from_dict(config_dict: dict) -> None:
    """Load agents API configuration from a dictionary."""
    global _agents_api_config
    _agents_api_config = AgentsApiConfig(**config_dict)
