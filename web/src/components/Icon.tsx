import type { SVGProps } from 'react';

export type IconName =
  | 'dashboard'
  | 'map'
  | 'layers'
  | 'image'
  | 'settings'
  | 'admin'
  | 'plus'
  | 'upload'
  | 'cursor'
  | 'point'
  | 'line'
  | 'polygon'
  | 'ruler'
  | 'area'
  | 'search'
  | 'close'
  | 'chevron-left'
  | 'chevron-right'
  | 'filter'
  | 'external'
  | 'database'
  | 'user'
  | 'logout'
  | 'check'
  | 'table';

const paths: Record<IconName, JSX.Element> = {
  dashboard: (
    <>
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
    </>
  ),
  map: (
    <>
      <path d="M9 18 3 21V6l6-3 6 3 6-3v15l-6 3-6-3Z" />
      <path d="M9 3v15M15 6v15" />
    </>
  ),
  layers: (
    <>
      <path d="m12 3 9 5-9 5-9-5 9-5Z" />
      <path d="m3 12 9 5 9-5M3 16l9 5 9-5" />
    </>
  ),
  image: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="1.5" />
      <circle cx="8.5" cy="9" r="1.5" />
      <path d="m21 15-5-5L5 20" />
    </>
  ),
  settings: (
    <>
      <path d="M4 6h10M18 6h2M4 12h2M10 12h10M4 18h7M15 18h5" />
      <circle cx="16" cy="6" r="2" />
      <circle cx="8" cy="12" r="2" />
      <circle cx="13" cy="18" r="2" />
    </>
  ),
  admin: (
    <>
      <path d="M12 3 4 6v5c0 5 3.5 8 8 10 4.5-2 8-5 8-10V6l-8-3Z" />
      <path d="m9 12 2 2 4-4" />
    </>
  ),
  plus: <path d="M12 5v14M5 12h14" />,
  upload: (
    <>
      <path d="M12 16V4m0 0L7 9m5-5 5 5" />
      <path d="M5 16v3h14v-3" />
    </>
  ),
  cursor: <path d="m5 3 5.5 17 2.5-6.5L20 11 5 3Z" />,
  point: (
    <>
      <circle cx="12" cy="12" r="3" />
      <circle cx="12" cy="12" r="8" />
    </>
  ),
  line: <path d="M4 18 20 6" />,
  polygon: <path d="m12 3 8 5.5-3 9.5H7L4 8.5 12 3Z" />,
  ruler: (
    <>
      <path d="m4 16 12-12 4 4L8 20l-4-4Z" />
      <path d="m9 7 2 2M12 10l2 2M7 9l2 2" />
    </>
  ),
  area: (
    <>
      <path d="M4 8V4h4M20 8V4h-4M4 16v4h4M20 16v4h-4" />
      <path d="m9 15 6-6" />
    </>
  ),
  search: (
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-4-4" />
    </>
  ),
  close: <path d="M6 6l12 12M18 6 6 18" />,
  'chevron-left': <path d="m15 18-6-6 6-6" />,
  'chevron-right': <path d="m9 18 6-6-6-6" />,
  filter: <path d="M4 5h16l-6 7v6l-4 2v-8L4 5Z" />,
  external: (
    <>
      <path d="M14 4h6v6M20 4l-9 9" />
      <path d="M18 14v5H5V6h5" />
    </>
  ),
  database: (
    <>
      <ellipse cx="12" cy="5" rx="8" ry="3" />
      <path d="M4 5v7c0 1.7 3.6 3 8 3s8-1.3 8-3V5" />
      <path d="M4 12v7c0 1.7 3.6 3 8 3s8-1.3 8-3v-7" />
    </>
  ),
  user: (
    <>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21c0-4 3.6-7 8-7s8 3 8 7" />
    </>
  ),
  logout: (
    <>
      <path d="M10 5H4v14h6M14 8l4 4-4 4M8 12h10" />
    </>
  ),
  check: <path d="m5 12 4 4L19 6" />,
  table: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="1.5" />
      <path d="M3 9h18M9 9v11" />
    </>
  ),
};

export default function Icon({
  name,
  size = 18,
  strokeWidth = 1.75,
  ...rest
}: { name: IconName; size?: number; strokeWidth?: number } & SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      {paths[name]}
    </svg>
  );
}
