"use client";

import { DEFAULT_AVATAR_SIZE_PX } from "@/lib/constants";
import Image from "next/image";

export const EVA_AVATAR_SRC = "/eva.jpg";

export interface EvaAvatarProps {
  size?: number;
  alt?: string;
}

export default function EvaAvatar({
  size = DEFAULT_AVATAR_SIZE_PX,
  alt = "Eva avatar",
}: EvaAvatarProps) {
  return (
    <div
      className="aspect-square rounded-full overflow-hidden relative shrink-0"
      style={{ height: size, width: size }}
    >
      <Image
        alt={alt}
        src={EVA_AVATAR_SRC}
        fill
        className="object-cover object-center"
        sizes={`${size}px`}
      />
    </div>
  );
}
