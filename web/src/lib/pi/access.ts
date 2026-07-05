import type { User } from "@/lib/types";

export const PI_ALLOWED_EMAIL = "30939235@qq.com";

export function isPiAllowedUser(user: Pick<User, "email"> | null): boolean {
  return user?.email?.toLowerCase() === PI_ALLOWED_EMAIL;
}
