import type { User } from "@/lib/types";

export const BLACKBOARD_ALLOWED_EMAIL = "30939235@qq.com";

export function isBlackboardAllowedUser(
  user: Pick<User, "email"> | null
): boolean {
  return user?.email?.toLowerCase() === BLACKBOARD_ALLOWED_EMAIL;
}
