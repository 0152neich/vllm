"""Regression tests cho cấu hình deployment thực tế."""

from pathlib import Path

from app.core.config import Settings


def test_deployment_routes_qwen3_4b_consistently() -> None:
    """Public catalog và default policy phải khớp model vLLM deployment."""

    config_path = (
        Path(__file__).resolve().parents[1] / "resources" / "configs" / "app.yaml"
    )
    settings = Settings.from_yaml(config_path)

    assert settings.upstream.model_map == {
        "qwen3-4b": "Qwen/Qwen3-4B-AWQ",
    }
    assert settings.defaults.allowed_models == ["qwen3-4b"]
