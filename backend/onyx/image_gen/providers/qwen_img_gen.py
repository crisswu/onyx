from __future__ import annotations

import base64
from datetime import datetime
from typing import Any

import httpx
from litellm.types.utils import ImageObject
from litellm.types.utils import ImageResponse

from onyx.image_gen.interfaces import ImageGenerationProvider
from onyx.image_gen.interfaces import ImageGenerationProviderCredentials
from onyx.image_gen.interfaces import ReferenceImage
from onyx.tracing.flows import LLMFlow
from onyx.tracing.llm_utils import traced_llm_call


_MULTIMODAL_GENERATION_PATH = "/services/aigc/multimodal-generation/generation"
_DEFAULT_TIMEOUT_SECONDS = 180.0


class QwenImageGenerationProvider(ImageGenerationProvider):
    def __init__(
        self,
        api_key: str,
        api_base: str,
    ) -> None:
        self._api_key = api_key
        self._api_base = api_base.rstrip("/")

    @classmethod
    def validate_credentials(
        cls,
        credentials: ImageGenerationProviderCredentials,
    ) -> bool:
        return bool(credentials.api_key and credentials.api_base)

    @classmethod
    def _build_from_credentials(
        cls,
        credentials: ImageGenerationProviderCredentials,
    ) -> QwenImageGenerationProvider:
        assert credentials.api_key
        assert credentials.api_base

        return cls(
            api_key=credentials.api_key,
            api_base=credentials.api_base,
        )

    @property
    def supports_reference_images(self) -> bool:
        return True

    @property
    def max_reference_images(self) -> int:
        return 3

    def generate_image(
        self,
        prompt: str,
        model: str,
        size: str,
        n: int,
        quality: str | None = None,  # noqa: ARG002
        reference_images: list[ReferenceImage] | None = None,
        **kwargs: Any,
    ) -> ImageResponse:
        if reference_images and len(reference_images) > self.max_reference_images:
            raise ValueError(
                "Qwen image generation supports at most "
                f"{self.max_reference_images} reference images."
            )

        parameters: dict[str, Any] = {
            "size": _normalize_size(size),
            "n": n,
            "watermark": False,
            "prompt_extend": True,
        }
        response_format = kwargs.pop("response_format", None)
        if response_format not in (None, "b64_json"):
            raise ValueError(f"Unsupported response_format for Qwen: {response_format}")

        for key in ("negative_prompt", "prompt_extend", "watermark", "seed"):
            if key in kwargs and kwargs[key] is not None:
                parameters[key] = kwargs[key]

        content = [
            *[
                {"image": _reference_image_to_data_uri(reference_image)}
                for reference_image in reference_images or []
            ],
            {"text": prompt},
        ]

        payload = {
            "model": model,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": content,
                    }
                ]
            },
            "parameters": parameters,
        }

        with traced_llm_call(
            flow=(
                LLMFlow.IMAGE_EDIT
                if reference_images
                else LLMFlow.IMAGE_GENERATION
            ),
            model=model,
            provider="qwen",
            input_messages=[{"role": "user", "content": prompt}],
        ):
            with httpx.Client(timeout=_DEFAULT_TIMEOUT_SECONDS) as client:
                api_response = client.post(
                    _build_generation_url(self._api_base),
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                _raise_for_qwen_error(api_response)
                image_urls = _extract_image_urls(api_response.json())
                generated_images = [
                    ImageObject(
                        b64_json=_download_image_as_base64(client, image_url),
                        revised_prompt=prompt,
                    )
                    for image_url in image_urls
                ]

        if not generated_images:
            raise RuntimeError("No image data returned from Qwen.")

        return ImageResponse(
            created=int(datetime.now().timestamp()),
            data=generated_images,
        )


def _build_generation_url(api_base: str) -> str:
    if api_base.endswith(_MULTIMODAL_GENERATION_PATH):
        return api_base
    return f"{api_base}{_MULTIMODAL_GENERATION_PATH}"


def _normalize_size(size: str) -> str:
    return size.replace("x", "*")


def _reference_image_to_data_uri(reference_image: ReferenceImage) -> str:
    image_data = base64.b64encode(reference_image.data).decode("utf-8")
    return f"data:{reference_image.mime_type};base64,{image_data}"


def _raise_for_qwen_error(response: httpx.Response) -> None:
    try:
        payload = response.json()
    except ValueError:
        response.raise_for_status()
        raise RuntimeError("Qwen image generation failed with an invalid response.")

    if response.is_success:
        if not payload.get("code"):
            return

    code = payload.get("code") or response.status_code
    message = payload.get("message") or response.text
    raise RuntimeError(f"Qwen image generation failed: {code}: {message}")


def _extract_image_urls(payload: dict[str, Any]) -> list[str]:
    output = payload.get("output", {})
    if not isinstance(output, dict):
        raise RuntimeError("Qwen image generation response has invalid output.")

    choices = output.get("choices", [])
    if not isinstance(choices, list):
        raise RuntimeError("Qwen image generation response has invalid choices.")

    image_urls: list[str] = []
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message", {})
        if not isinstance(message, dict):
            continue
        content = message.get("content", [])
        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict):
                continue
            image_url = item.get("image")
            if isinstance(image_url, str) and image_url:
                image_urls.append(image_url)

    return image_urls


def _download_image_as_base64(client: httpx.Client, image_url: str) -> str:
    image_response = client.get(image_url)
    image_response.raise_for_status()
    return base64.b64encode(image_response.content).decode("utf-8")
