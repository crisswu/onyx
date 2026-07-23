"use client";

import { MinimalAgent } from "@/lib/agents/types";
import { buildAgentAvatarUrl } from "@/lib/agents/utils";
import { DEFAULT_AVATAR_SIZE_PX, DEFAULT_AGENT_ID } from "@/lib/constants";
import CustomAgentAvatar from "@/refresh-components/avatars/CustomAgentAvatar";
import EvaAvatar from "@/refresh-components/avatars/EvaAvatar";

export interface AgentAvatarProps {
  agent: MinimalAgent;
  size?: number;
}

export default function AgentAvatar({
  agent,
  size = DEFAULT_AVATAR_SIZE_PX,
  ...props
}: AgentAvatarProps) {
  if (agent.id === DEFAULT_AGENT_ID) {
    return <EvaAvatar size={size} />;
  }

  return (
    <CustomAgentAvatar
      name={agent.name}
      src={agent.uploaded_image_id ? buildAgentAvatarUrl(agent.id) : undefined}
      iconName={agent.icon_name}
      size={size}
      {...props}
    />
  );
}
