"use client";

import * as Yup from "yup";
import { FormikField } from "@/refresh-components/form/FormikField";
import { FormField } from "@/refresh-components/form/FormField";
import { InputTypeIn } from "@opal/components";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import InlineExternalLink from "@/refresh-components/InlineExternalLink";
import { ImageGenFormWrapper } from "@/refresh-pages/admin/ImageGenerationPage/forms/ImageGenFormWrapper";
import {
  ImageGenFormBaseProps,
  ImageGenFormChildProps,
  ImageGenSubmitPayload,
} from "@/refresh-pages/admin/ImageGenerationPage/forms/types";
import { ImageProvider } from "@/refresh-pages/admin/ImageGenerationPage/constants";
import { ImageGenerationCredentials } from "@/refresh-pages/admin/ImageGenerationPage/svc";

interface QwenImageGenFormValues {
  api_key: string;
  api_base: string;
}

const QWEN_PROVIDER_NAME = "qwen";
const DEFAULT_API_BASE =
  "https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api/v1";

const initialValues: QwenImageGenFormValues = {
  api_key: "",
  api_base: "",
};

const validationSchema = Yup.object().shape({
  api_key: Yup.string().required("API Key is required"),
  api_base: Yup.string().required("API Base URL is required"),
});

function getInitialValuesFromCredentials(
  credentials: ImageGenerationCredentials,
  _imageProvider: ImageProvider
): Partial<QwenImageGenFormValues> {
  return {
    api_key: credentials.api_key || "",
    api_base: credentials.api_base || "",
  };
}

function transformValues(
  values: QwenImageGenFormValues,
  imageProvider: ImageProvider
): ImageGenSubmitPayload {
  return {
    modelName: imageProvider.model_name,
    imageProviderId: imageProvider.image_provider_id,
    provider: QWEN_PROVIDER_NAME,
    apiKey: values.api_key,
    apiBase: values.api_base,
  };
}

function QwenFormFields(props: ImageGenFormChildProps<QwenImageGenFormValues>) {
  const {
    apiStatus,
    showApiMessage,
    errorMessage,
    disabled,
    isLoadingCredentials,
    resetApiState,
    imageProvider,
  } = props;

  return (
    <>
      <FormikField<string>
        name="api_key"
        render={(field, _helper, meta, state) => (
          <FormField
            name="api_key"
            state={apiStatus === "error" ? "error" : state}
            className="w-full"
          >
            <FormField.Label>API Key</FormField.Label>
            <FormField.Control>
              <PasswordInputTypeIn
                {...field}
                onChange={(e) => {
                  field.onChange(e);
                  resetApiState();
                }}
                placeholder={
                  isLoadingCredentials
                    ? "Loading..."
                    : "Enter your DashScope API key"
                }
                disabled={disabled}
                error={apiStatus === "error"}
              />
            </FormField.Control>
            {showApiMessage ? (
              <FormField.APIMessage
                state={apiStatus}
                messages={{
                  loading: `Testing API key with ${imageProvider.title}...`,
                  success: "API key is valid. Configuration saved.",
                  error: errorMessage || "Invalid API key",
                }}
              />
            ) : (
              <FormField.Message
                messages={{
                  idle: (
                    <>
                      {
                        "Use a Model Studio API key for the same region as the API base. "
                      }
                      <InlineExternalLink href="https://help.aliyun.com/en/model-studio/get-api-key">
                        Get an API key
                      </InlineExternalLink>
                      {"."}
                    </>
                  ),
                  error: meta.error,
                }}
              />
            )}
          </FormField>
        )}
      />

      <FormikField<string>
        name="api_base"
        render={(field, helper, meta, state) => (
          <FormField name="api_base" state={state} className="w-full">
            <FormField.Label>API Base URL</FormField.Label>
            <FormField.Control>
              <InputTypeIn
                value={field.value}
                onChange={(e) => {
                  helper.setValue(e.target.value);
                  resetApiState();
                }}
                onBlur={field.onBlur}
                placeholder={DEFAULT_API_BASE}
                variant={disabled ? "disabled" : undefined}
              />
            </FormField.Control>
            <FormField.Message
              messages={{
                idle: (
                  <>
                    {
                      "Use the regional Model Studio base URL containing your workspace ID. See "
                    }
                    <InlineExternalLink href="https://help.aliyun.com/en/model-studio/qwen-image-api">
                      Qwen-Image API docs
                    </InlineExternalLink>
                    {"."}
                  </>
                ),
                error: meta.error,
              }}
            />
          </FormField>
        )}
      />
    </>
  );
}

export function QwenImageGenForm(props: ImageGenFormBaseProps) {
  const { imageProvider, existingConfig } = props;

  return (
    <ImageGenFormWrapper<QwenImageGenFormValues>
      {...props}
      title={
        existingConfig
          ? `Edit ${imageProvider.title}`
          : `Connect ${imageProvider.title}`
      }
      description={imageProvider.description}
      initialValues={initialValues}
      validationSchema={validationSchema}
      getInitialValuesFromCredentials={getInitialValuesFromCredentials}
      transformValues={(values) => transformValues(values, imageProvider)}
    >
      {(childProps) => <QwenFormFields {...childProps} />}
    </ImageGenFormWrapper>
  );
}
