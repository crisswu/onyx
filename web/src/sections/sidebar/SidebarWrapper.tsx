"use client";

import React from "react";
import { SidebarLayouts } from "@opal/layouts";
import { useShowLogoWhenFolded } from "@/lib/sidebar/hooks";
import EvaAvatar from "@/refresh-components/avatars/EvaAvatar";

/**
 * Renders the app-branded logo for use as the `logo` prop on sidebar primitives.
 * Exported so other sidebar entry points (e.g. AdminSidebar) can reuse it.
 */
export function renderAppLogo(folded: boolean | undefined): React.ReactNode {
  if (!folded) {
    return (
      <div className="flex items-center gap-2 px-1">
        <EvaAvatar size={28} />
        <span className="text-lg font-semibold leading-none text-text-05">
          Eva
        </span>
      </div>
    );
  }

  return (
    <div className="px-1">
      <EvaAvatar size={28} />
    </div>
  );
}

export interface SidebarWrapperProps {
  foldable?: boolean;
  children?: React.ReactNode;
}

/**
 * App-specific sidebar wrapper. Thin shell around `SidebarLayouts.Root`
 * that injects the enterprise-aware logo and show/hide rules.
 */
export default function SidebarWrapper({
  foldable = false,
  children,
}: SidebarWrapperProps) {
  const showLogoWhenFolded = useShowLogoWhenFolded();

  return (
    <SidebarLayouts.Root foldable={foldable}>
      <SidebarLayouts.Header
        logo={renderAppLogo}
        showLogoWhenFolded={showLogoWhenFolded}
      />
      {children}
    </SidebarLayouts.Root>
  );
}
