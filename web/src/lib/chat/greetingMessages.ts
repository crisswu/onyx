export const GREETING_MESSAGES = ["我可以帮你做什么？", "我们开始吧。"];

export function getRandomGreeting(): string {
  return GREETING_MESSAGES[
    Math.floor(Math.random() * GREETING_MESSAGES.length)
  ] as string;
}
