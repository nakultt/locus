"use client";

import Image from "next/image";
import { useReducedMotion } from "framer-motion";

/**
 * The tools Locus connects to, scrolling past.
 *
 * A CSS animation on a duplicated track rather than a JS loop: the browser can
 * run a transform on the compositor without waking React sixty times a second,
 * and the whole thing costs one keyframe.
 *
 * The list is duplicated exactly once and the track translates by half its
 * width, which is what makes the wrap seamless — animating a single copy snaps
 * back visibly at the end of every pass.
 *
 * These are real logos of real products, presented as "what this connects to",
 * which is what they are. Nothing here claims endorsement.
 */

const TOOLS = [
  { name: "GitHub", logo: "/github.svg" },
  { name: "Jira", logo: "/jira.svg" },
  { name: "Slack", logo: "/slack.svg" },
  { name: "Linear", logo: "/linear.svg" },
  { name: "Gmail", logo: "/gmail.svg" },
  { name: "Google Calendar", logo: "/calendar.svg" },
  { name: "Google Docs", logo: "/docs.svg" },
  { name: "Google Drive", logo: "/drive.svg" },
  { name: "Google Sheets", logo: "/sheets.svg" },
  { name: "Google Meet", logo: "/meet.svg" },
  { name: "Notion", logo: "/notion.png" },
];

function Logo({ name, logo }: { name: string; logo: string }) {
  return (
    <span className="flex shrink-0 items-center gap-2.5 opacity-70 grayscale transition duration-300 hover:opacity-100 hover:grayscale-0">
      <Image
        src={logo}
        alt=""
        width={22}
        height={22}
        unoptimized
        className="size-[22px] object-contain"
      />
      <span className="whitespace-nowrap text-sm font-medium text-muted">
        {name}
      </span>
    </span>
  );
}

export function ToolMarquee() {
  const still = useReducedMotion();

  return (
    <div
      className="relative overflow-hidden"
      role="list"
      aria-label="Connects to GitHub, Jira, Slack, Linear, Gmail, Google Calendar, Google Docs, Google Drive, Google Sheets, Google Meet and Notion"
    >
      {/* Faded at both edges so the row reads as continuing past the viewport
          rather than being cut off by it. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-y-0 left-0 z-10 w-24 bg-gradient-to-r from-bg to-transparent"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-y-0 right-0 z-10 w-24 bg-gradient-to-l from-bg to-transparent"
      />

      {still ? (
        // Stopped, and laid out to be read rather than scrolled past.
        <div className="flex flex-wrap items-center justify-center gap-x-10 gap-y-4 py-2">
          {TOOLS.map((tool) => (
            <Logo key={tool.name} {...tool} />
          ))}
        </div>
      ) : (
        <div className="flex w-max animate-[marquee_38s_linear_infinite] py-2">
          {/* Two halves of *identical* width, which is what makes the wrap
              seamless. A single flat list with a uniform gap does not work:
              translating by -50% then lands half a gap away from the second
              copy's first item, and the row visibly jumps once per pass. Each
              half carries its own trailing gap as padding, so half the track
              is exactly one half's width. */}
          {[0, 1].map((half) => (
            <div
              key={half}
              aria-hidden={half === 1}
              className="flex shrink-0 items-center gap-10 pr-10"
            >
              {TOOLS.map((tool) => (
                <Logo key={`${half}-${tool.name}`} {...tool} />
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
