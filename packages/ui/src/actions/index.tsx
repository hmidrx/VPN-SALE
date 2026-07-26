import React from "react";
import { cx } from "../internal/cx";

export type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  loading?: boolean;
};
export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", loading = false, disabled, className, children, ...props }, ref,
) {
  return <button ref={ref} className={cx("ui-button", `ui-button--${variant}`, className)} disabled={disabled || loading} aria-busy={loading || undefined} {...props}>{loading && <span className="ui-spinner" aria-hidden="true" />}{children}</button>;
});

type AccessibleName = { "aria-label": string; "aria-labelledby"?: string } | { "aria-label"?: string; "aria-labelledby": string };
export type IconButtonProps = ButtonProps & AccessibleName;
export const IconButton = React.forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(props, ref) {
  if (!props["aria-label"] && !props["aria-labelledby"]) throw new Error("IconButton requires an accessible name");
  return <Button {...props} ref={ref} className={cx("ui-icon-button", props.className)} />;
});

export function LinkButton({ variant = "primary", className, disabled = false, onClick, href, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { variant?: ButtonProps["variant"]; disabled?: boolean }) {
  if (disabled) return <span className={cx("ui-button", `ui-button--${variant}`, className)} aria-disabled="true" {...(props as React.HTMLAttributes<HTMLSpanElement>)} />;
  return <a className={cx("ui-button", `ui-button--${variant}`, className)} href={href} onClick={onClick} {...props} />;
}
