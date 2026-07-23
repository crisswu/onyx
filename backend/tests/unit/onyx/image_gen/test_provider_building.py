import json
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from onyx.image_gen.exceptions import ImageProviderCredentialsError
from onyx.image_gen.factory import get_image_generation_provider
from onyx.image_gen.interfaces import ImageGenerationProviderCredentials
from onyx.image_gen.interfaces import ReferenceImage
from onyx.image_gen.providers.azure_img_gen import AzureImageGenerationProvider
from onyx.image_gen.providers.openai_img_gen import OpenAIImageGenerationProvider
from onyx.image_gen.providers.qwen_img_gen import QwenImageGenerationProvider
from onyx.image_gen.providers.vertex_img_gen import VertexImageGenerationProvider

OPENAI_PROVIDER = "openai"
AZURE_PROVIDER = "azure"
QWEN_PROVIDER = "qwen"
VERTEX_PROVIDER = "vertex_ai"


def _get_default_image_gen_creds() -> ImageGenerationProviderCredentials:
    return ImageGenerationProviderCredentials(
        api_key=None,
        api_base=None,
        api_version=None,
        deployment_name=None,
        custom_config=None,
    )


def test_request_provider_that_no_exist() -> None:
    provider = "nonexistent"
    credentials = _get_default_image_gen_creds()

    with pytest.raises(ValueError):
        get_image_generation_provider(provider, credentials)


def test_build_openai_provider_from_api_key_and_base() -> None:
    credentials = _get_default_image_gen_creds()

    credentials.api_key = "test"
    credentials.api_base = "test"

    provider = OPENAI_PROVIDER

    image_gen_provider = get_image_generation_provider(provider, credentials)

    assert isinstance(image_gen_provider, OpenAIImageGenerationProvider)
    assert image_gen_provider._api_key == "test"
    assert image_gen_provider._api_base == "test"
    assert image_gen_provider.supports_reference_images is True
    assert image_gen_provider.max_reference_images == 16


def test_build_openai_provider_fails_no_api_key() -> None:
    credentials = _get_default_image_gen_creds()

    credentials.api_base = "test"

    provider = OPENAI_PROVIDER

    with pytest.raises(ImageProviderCredentialsError):
        get_image_generation_provider(provider, credentials)


def test_build_azure_provider_from_api_key_and_base_and_version() -> None:
    credentials = _get_default_image_gen_creds()

    credentials.api_key = "test"
    credentials.api_base = "test"
    credentials.api_version = "test"

    provider = AZURE_PROVIDER

    image_gen_provider = get_image_generation_provider(provider, credentials)

    assert isinstance(image_gen_provider, AzureImageGenerationProvider)
    assert image_gen_provider._api_key == "test"
    assert image_gen_provider._api_base == "test"
    assert image_gen_provider._api_version == "test"
    assert image_gen_provider.supports_reference_images is True
    assert image_gen_provider.max_reference_images == 16


def test_build_azure_provider_fails_missing_credential() -> None:
    azure_required = [
        "api_key",
        "api_base",
        "api_version",
    ]

    default_creds = _get_default_image_gen_creds()
    default_creds.api_key = "test"
    default_creds.api_base = "test"
    default_creds.api_version = "test"

    for attribute in azure_required:
        credentials = default_creds.model_copy()
        setattr(credentials, attribute, None)

        with pytest.raises(ImageProviderCredentialsError):
            get_image_generation_provider(AZURE_PROVIDER, credentials)


def test_build_qwen_provider_from_api_key_and_base() -> None:
    credentials = _get_default_image_gen_creds()

    credentials.api_key = "test-key"
    credentials.api_base = "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1"

    image_gen_provider = get_image_generation_provider(QWEN_PROVIDER, credentials)

    assert isinstance(image_gen_provider, QwenImageGenerationProvider)
    assert image_gen_provider._api_key == "test-key"
    assert (
        image_gen_provider._api_base
        == "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1"
    )
    assert image_gen_provider.supports_reference_images is True
    assert image_gen_provider.max_reference_images == 3


def test_build_qwen_provider_normalizes_openai_compatible_base() -> None:
    credentials = _get_default_image_gen_creds()

    credentials.api_key = "test-key"
    credentials.api_base = (
        "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    )

    image_gen_provider = get_image_generation_provider(QWEN_PROVIDER, credentials)

    assert isinstance(image_gen_provider, QwenImageGenerationProvider)
    assert (
        image_gen_provider._api_base
        == "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1"
    )


def test_build_qwen_provider_fails_missing_credential() -> None:
    default_creds = _get_default_image_gen_creds()
    default_creds.api_key = "test-key"
    default_creds.api_base = "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1"

    for attribute in ["api_key", "api_base"]:
        credentials = default_creds.model_copy()
        setattr(credentials, attribute, None)

        with pytest.raises(ImageProviderCredentialsError):
            get_image_generation_provider(QWEN_PROVIDER, credentials)


def test_build_vertex_provider_from_credentials() -> None:
    credentials = _get_default_image_gen_creds()

    vertex_credentials = {
        "project_id": "demo_project_1",
        "private_key_id": "test",
    }

    vertex_json = json.dumps(vertex_credentials)
    credentials.custom_config = {
        "vertex_credentials": vertex_json,
        "vertex_location": "global",
    }
    provider = VERTEX_PROVIDER

    image_gen_provider = get_image_generation_provider(provider, credentials)

    assert isinstance(image_gen_provider, VertexImageGenerationProvider)
    assert image_gen_provider._vertex_credentials == vertex_json
    assert image_gen_provider._vertex_location == "global"
    assert image_gen_provider._vertex_project == "demo_project_1"


def test_build_vertex_provider_with_missing_project_id() -> None:
    credentials = _get_default_image_gen_creds()

    vertex_credentials = {
        "private_key_id": "test",
    }

    vertex_json = json.dumps(vertex_credentials)
    credentials.custom_config = {
        "vertex_credentials": vertex_json,
        "vertex_location": "global",
    }

    with pytest.raises(ImageProviderCredentialsError):
        get_image_generation_provider("vertex_ai", credentials)


def test_openai_provider_uses_image_generation_without_reference_images() -> None:
    provider = OpenAIImageGenerationProvider(
        api_key="test-key",
        api_base="test-base",
    )
    expected_response = object()

    with (
        patch("litellm.image_generation", return_value=expected_response) as mock_gen,
        patch("litellm.image_edit") as mock_edit,
    ):
        response = provider.generate_image(
            prompt="draw a mountain",
            model="gpt-image-1",
            size="1024x1024",
            n=1,
            quality="high",
        )

    assert response is expected_response
    mock_gen.assert_called_once()
    mock_edit.assert_not_called()


def test_openai_provider_uses_image_edit_with_reference_images() -> None:
    provider = OpenAIImageGenerationProvider(
        api_key="test-key",
        api_base="test-base",
    )
    reference_images = [
        ReferenceImage(data=b"image-1-bytes", mime_type="image/png"),
        ReferenceImage(data=b"image-2-bytes", mime_type="image/jpeg"),
    ]
    expected_response = object()

    with (
        patch("litellm.image_generation") as mock_gen,
        patch("litellm.image_edit", return_value=expected_response) as mock_edit,
    ):
        response = provider.generate_image(
            prompt="make this look watercolor",
            model="gpt-image-1",
            size="1024x1024",
            n=1,
            quality="high",
            reference_images=reference_images,
        )

    assert response is expected_response
    mock_gen.assert_not_called()
    mock_edit.assert_called_once()
    assert mock_edit.call_args.kwargs["image"] == [
        b"image-1-bytes",
        b"image-2-bytes",
    ]


def test_openai_provider_rejects_reference_images_for_unsupported_model() -> None:
    provider = OpenAIImageGenerationProvider(api_key="test-key")

    with pytest.raises(ValueError):
        provider.generate_image(
            prompt="edit this image",
            model="unsupported-model",
            size="1024x1024",
            n=1,
            reference_images=[ReferenceImage(data=b"image-1", mime_type="image/png")],
        )


def test_azure_provider_uses_image_generation_without_reference_images() -> None:
    provider = AzureImageGenerationProvider(
        api_key="test-key",
        api_base="https://azure.example.com",
        api_version="2024-05-01-preview",
        deployment_name="img-deployment",
    )
    expected_response = object()

    with (
        patch("litellm.image_generation", return_value=expected_response) as mock_gen,
        patch("litellm.image_edit") as mock_edit,
    ):
        response = provider.generate_image(
            prompt="draw a skyline",
            model="gpt-image-1",
            size="1024x1024",
            n=1,
            quality="high",
        )

    assert response is expected_response
    mock_gen.assert_called_once()
    mock_edit.assert_not_called()
    assert mock_gen.call_args.kwargs["model"] == "azure/img-deployment"


def test_azure_provider_uses_image_edit_with_reference_images() -> None:
    provider = AzureImageGenerationProvider(
        api_key="test-key",
        api_base="https://azure.example.com",
        api_version="2024-05-01-preview",
        deployment_name="img-deployment",
    )
    reference_images = [
        ReferenceImage(data=b"image-1-bytes", mime_type="image/png"),
        ReferenceImage(data=b"image-2-bytes", mime_type="image/jpeg"),
    ]
    expected_response = object()

    with (
        patch("litellm.image_generation") as mock_gen,
        patch("litellm.image_edit", return_value=expected_response) as mock_edit,
    ):
        response = provider.generate_image(
            prompt="make this noir style",
            model="gpt-image-1",
            size="1024x1024",
            n=1,
            quality="high",
            reference_images=reference_images,
        )

    assert response is expected_response
    mock_gen.assert_not_called()
    mock_edit.assert_called_once()
    assert mock_edit.call_args.kwargs["model"] == "azure/img-deployment"
    assert mock_edit.call_args.kwargs["image"] == [
        b"image-1-bytes",
        b"image-2-bytes",
    ]


def test_azure_provider_rejects_reference_images_for_unsupported_model() -> None:
    provider = AzureImageGenerationProvider(
        api_key="test-key",
        api_base="https://azure.example.com",
        api_version="2024-05-01-preview",
    )

    with pytest.raises(ValueError):
        provider.generate_image(
            prompt="edit this image",
            model="unsupported-model",
            size="1024x1024",
            n=1,
            reference_images=[ReferenceImage(data=b"image-1", mime_type="image/png")],
        )


def test_qwen_provider_calls_dashscope_and_returns_base64() -> None:
    provider = QwenImageGenerationProvider(
        api_key="test-key",
        api_base="https://workspace.cn-beijing.maas.aliyuncs.com/api/v1",
    )
    requests_seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(request)
        if request.method == "POST":
            assert (
                str(request.url)
                == "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
            )
            assert request.headers["Authorization"] == "Bearer test-key"
            request_body = json.loads(request.content)
            assert request_body["model"] == "qwen-image-3.0-pro"
            assert request_body["input"]["messages"][0]["content"] == [
                {"text": "draw a mountain"}
            ]
            assert request_body["parameters"]["size"] == "1024*1024"
            assert request_body["parameters"]["n"] == 1
            return httpx.Response(
                200,
                json={
                    "output": {
                        "choices": [
                            {
                                "message": {
                                    "content": [
                                        {"image": "https://example.com/image.png"}
                                    ]
                                }
                            }
                        ]
                    }
                },
            )

        if str(request.url) == "https://example.com/image.png":
            return httpx.Response(200, content=b"fake-png-bytes")

        return httpx.Response(404)

    transport = httpx.MockTransport(handler)

    with patch(
        "onyx.image_gen.providers.qwen_img_gen.httpx.Client",
        side_effect=lambda **_: httpx.Client(transport=transport),
    ):
        response = provider.generate_image(
            prompt="draw a mountain",
            model="qwen-image-3.0-pro",
            size="1024x1024",
            n=1,
        )

    assert len(requests_seen) == 2
    assert response.data
    assert response.data[0].b64_json == "ZmFrZS1wbmctYnl0ZXM="
    assert response.data[0].revised_prompt == "draw a mountain"


def test_qwen_provider_accepts_openai_compatible_base_url() -> None:
    provider = QwenImageGenerationProvider(
        api_key="test-key",
        api_base="https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    )
    post_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            post_urls.append(str(request.url))
            return httpx.Response(
                200,
                json={
                    "output": {
                        "choices": [
                            {
                                "message": {
                                    "content": [
                                        {"image": "https://example.com/image.png"}
                                    ]
                                }
                            }
                        ]
                    }
                },
            )

        if str(request.url) == "https://example.com/image.png":
            return httpx.Response(200, content=b"fake-png-bytes")

        return httpx.Response(404)

    transport = httpx.MockTransport(handler)

    with patch(
        "onyx.image_gen.providers.qwen_img_gen.httpx.Client",
        side_effect=lambda **_: httpx.Client(transport=transport),
    ):
        provider.generate_image(
            prompt="draw a mountain",
            model="qwen-image-3.0-pro",
            size="1024x1024",
            n=1,
        )

    assert post_urls == [
        "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
    ]


def test_qwen_provider_reports_non_json_http_errors() -> None:
    provider = QwenImageGenerationProvider(
        api_key="test-key",
        api_base="https://workspace.cn-beijing.maas.aliyuncs.com/api/v1",
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    transport = httpx.MockTransport(handler)

    with (
        patch(
            "onyx.image_gen.providers.qwen_img_gen.httpx.Client",
            side_effect=lambda **_: httpx.Client(transport=transport),
        ),
        pytest.raises(RuntimeError, match="HTTP 404: not found"),
    ):
        provider.generate_image(
            prompt="draw a mountain",
            model="qwen-image-3.0-pro",
            size="1024x1024",
            n=1,
        )


def test_qwen_provider_sends_reference_images_as_data_uris() -> None:
    provider = QwenImageGenerationProvider(
        api_key="test-key",
        api_base="https://workspace.cn-beijing.maas.aliyuncs.com/api/v1",
    )
    post_payloads: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            post_payloads.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "output": {
                        "choices": [
                            {
                                "message": {
                                    "content": [
                                        {"image": "https://example.com/image.png"}
                                    ]
                                }
                            }
                        ]
                    }
                },
            )

        if str(request.url) == "https://example.com/image.png":
            return httpx.Response(200, content=b"fake-png-bytes")

        return httpx.Response(404)

    transport = httpx.MockTransport(handler)

    with patch(
        "onyx.image_gen.providers.qwen_img_gen.httpx.Client",
        side_effect=lambda **_: httpx.Client(transport=transport),
    ):
        response = provider.generate_image(
            prompt="edit this image",
            model="qwen-image-3.0-pro",
            size="1024x1024",
            n=1,
            reference_images=[
                ReferenceImage(data=b"image-1", mime_type="image/png"),
                ReferenceImage(data=b"image-2", mime_type="image/jpeg"),
            ],
        )

    assert response.data
    assert response.data[0].b64_json == "ZmFrZS1wbmctYnl0ZXM="
    assert post_payloads[0]["input"]["messages"][0]["content"] == [
        {"image": "data:image/png;base64,aW1hZ2UtMQ=="},
        {"image": "data:image/jpeg;base64,aW1hZ2UtMg=="},
        {"text": "edit this image"},
    ]


def test_qwen_provider_rejects_too_many_reference_images() -> None:
    provider = QwenImageGenerationProvider(
        api_key="test-key",
        api_base="https://workspace.cn-beijing.maas.aliyuncs.com/api/v1",
    )

    with pytest.raises(ValueError, match="at most 3 reference images"):
        provider.generate_image(
            prompt="edit this image",
            model="qwen-image-3.0-pro",
            size="1024x1024",
            n=1,
            reference_images=[
                ReferenceImage(data=b"image-1", mime_type="image/png"),
                ReferenceImage(data=b"image-2", mime_type="image/png"),
                ReferenceImage(data=b"image-3", mime_type="image/png"),
                ReferenceImage(data=b"image-4", mime_type="image/png"),
            ],
        )
