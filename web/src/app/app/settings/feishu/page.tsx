"use client";

import useSWR from "swr";
import { Button, Code, CopyButton, Text } from "@opal/components";
import { Content } from "@opal/layouts";
import { SvgKey, SvgTrash, SvgUnplug } from "@opal/icons";
import Card from "@/refresh-components/cards/Card";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { toast } from "@/hooks/useToast";

interface FeishuBindingStatus {
  is_bound: boolean;
  open_id: string | null;
  bind_code: string | null;
  bind_code_expires_at: string | null;
  bind_code_ttl_minutes: number;
}

interface FeishuBindingCodeResponse {
  bind_code: string;
  bind_code_expires_at: string;
  bind_code_ttl_minutes: number;
}

const FEISHU_BINDING_URL = "/api/feishu/binding";

function formatExpiry(value: string | null) {
  if (!value) {
    return "";
  }
  return new Date(value).toLocaleString();
}

export default function FeishuSettingsPage() {
  const {
    data: status,
    mutate,
    isLoading,
  } = useSWR<FeishuBindingStatus>(FEISHU_BINDING_URL, errorHandlingFetcher);

  const bindCommand = status?.bind_code ? `/bind ${status.bind_code}` : "";
  const bindCodeExpiresAt = status?.bind_code_expires_at ?? null;

  const generateCode = async () => {
    const response = await fetch(`${FEISHU_BINDING_URL}/code`, {
      method: "POST",
    });
    if (!response.ok) {
      toast({
        message: "Failed to create Feishu binding code",
        level: "error",
      });
      return;
    }

    const body = (await response.json()) as FeishuBindingCodeResponse;
    await mutate({
      is_bound: status?.is_bound ?? false,
      open_id: status?.open_id ?? null,
      bind_code: body.bind_code,
      bind_code_expires_at: body.bind_code_expires_at,
      bind_code_ttl_minutes: body.bind_code_ttl_minutes,
    });
  };

  const unbind = async () => {
    const response = await fetch(FEISHU_BINDING_URL, {
      method: "DELETE",
    });
    if (!response.ok) {
      toast({
        message: "Failed to disconnect Feishu",
        level: "error",
      });
      return;
    }
    await mutate();
  };

  return (
    <div className="flex flex-col gap-4 w-full max-w-2xl">
      <Content
        sizePreset="main-ui"
        variant="section"
        icon={SvgUnplug}
        title="Feishu"
        description="Connect this Onyx account to a Feishu chat identity."
      />

      <Card>
        <div className="flex flex-col gap-5 p-5">
          <div className="flex items-start justify-between gap-4">
            <div className="flex flex-col gap-1">
              <Text as="p" font="main-ui-action" color="text-02">
                Status
              </Text>
              <Text as="p" font="secondary-body" color="text-03">
                {isLoading
                  ? "Loading..."
                  : status?.is_bound
                    ? "Connected"
                    : "Not connected"}
              </Text>
              {status?.open_id && (
                <Text as="p" font="secondary-mono" color="text-04">
                  {status.open_id}
                </Text>
              )}
            </div>

            {status?.is_bound ? (
              <Button
                variant="danger"
                prominence="secondary"
                icon={SvgTrash}
                onClick={unbind}
              >
                Disconnect
              </Button>
            ) : (
              <Button
                variant="default"
                prominence="primary"
                icon={SvgKey}
                onClick={generateCode}
                disabled={isLoading}
              >
                Generate Code
              </Button>
            )}
          </div>

          {bindCommand && (
            <div className="flex flex-col gap-3">
              <Text as="p" font="secondary-body" color="text-03">
                Send this command to the Feishu bot.
              </Text>
              <div className="flex items-center gap-2">
                <Code showCopyButton={false}>{bindCommand}</Code>
                <CopyButton
                  getCopyText={() => bindCommand}
                  tooltip="Copy bind command"
                  prominence="tertiary"
                  size="sm"
                />
              </div>
              <Text as="p" font="secondary-body" color="text-04">
                {`Expires: ${formatExpiry(bindCodeExpiresAt)}`}
              </Text>
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}
