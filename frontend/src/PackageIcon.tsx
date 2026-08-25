import { PACKAGE_GLYPHS } from "./packageGlyphs";

interface PackageIconProps {
  category: number;
  className?: string;
  size?: number;
}

function PackageIcon({ category, className, size = 16 }: PackageIconProps) {
  const d = PACKAGE_GLYPHS[category] ?? PACKAGE_GLYPHS[0];
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.3"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d={d} />
    </svg>
  );
}

export default PackageIcon;
