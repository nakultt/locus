import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

/**
 * The custom steps of the type scale, named for tailwind-merge.
 *
 * This is not optional configuration. `twMerge` resolves conflicts by class
 * *group*, and it identifies a font size by shape — `text-sm`, `text-2xl`,
 * `text-[13px]`. It has no way to know that `text-body` is a size while
 * `text-primary-fg` is a colour, so it files both under `text-color`, decides
 * they conflict, and keeps only the last one written.
 *
 * The symptom was a black pill with an invisible label: `Button` composes
 * `"bg-primary text-primary-fg …"` with `"h-11 px-6 text-body"`, and the
 * colour was silently dropped from every large button in the product. The same
 * collision quietly reverted `text-label` wherever a kicker also set a colour.
 *
 * Any new step added to `@theme` in `globals.css` has to be named here too.
 */
const TYPE_SCALE = [
  "display",
  "hero",
  "title",
  "h1",
  "h2",
  "h3",
  "body",
  "label",
];

const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      "font-size": [{ text: TYPE_SCALE }],
    },
  },
});

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
