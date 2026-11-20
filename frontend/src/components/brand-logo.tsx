import Image from "next/image";

const logoSizes = {
  compact: { width: 40, height: 42, className: "size-8" },
  standard: { width: 48, height: 51, className: "size-10" },
  large: { width: 160, height: 170, className: "size-28" },
} as const;

export function BrandLogo({
  size = "standard",
  alt = "DevPilot",
  className,
}: {
  size?: keyof typeof logoSizes;
  alt?: string;
  className?: string;
}) {
  const dimensions = logoSizes[size];
  return (
    <Image
      src="/brand/logo.png"
      alt={alt}
      width={dimensions.width}
      height={dimensions.height}
      className={`${dimensions.className} shrink-0 object-contain${className ? ` ${className}` : ""}`}
      priority={size === "large"}
    />
  );
}
