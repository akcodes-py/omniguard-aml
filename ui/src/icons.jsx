// Minimal inline icon set (no external icon dependency).
const base = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round",
  strokeLinejoin: "round",
  viewBox: "0 0 24 24",
};

const I = ({ children, className = "w-5 h-5", ...rest }) => (
  <svg {...base} className={className} {...rest}>{children}</svg>
);

export const Search = (p) => <I {...p}><circle cx="11" cy="11" r="6.5" /><path d="M20 20l-4.2-4.2" /></I>;
export const Plus = (p) => <I {...p}><path d="M12 5v14M5 12h14" /></I>;
export const Flask = (p) => <I {...p}><path d="M9 3h6M10 3v6.2L5.4 17a2 2 0 001.8 3h9.6a2 2 0 001.8-3L14 9.2V3" /><path d="M7.5 15h9" /></I>;
export const Filter = (p) => <I {...p}><path d="M3 5h18l-7 8v6l-4 2v-8L3 5z" /></I>;
export const Info = (p) => <I {...p}><circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 7.6v.2" /></I>;
export const Menu = (p) => <I {...p}><path d="M4 7h16M4 12h10M4 17h13" /></I>;
export const X = (p) => <I {...p}><path d="M6 6l12 12M18 6L6 18" /></I>;
export const ChevronRight = (p) => <I {...p}><path d="M9 5l7 7-7 7" /></I>;
export const ChevronLeft = (p) => <I {...p}><path d="M15 5l-7 7 7 7" /></I>;
export const ChevronDown = (p) => <I {...p}><path d="M6 9l6 6 6-6" /></I>;
export const External = (p) => <I {...p}><path d="M14 4h6v6M20 4l-9 9" /><path d="M18 14v5a1 1 0 01-1 1H5a1 1 0 01-1-1V7a1 1 0 011-1h5" /></I>;
export const More = (p) => <I {...p}><circle cx="12" cy="5.5" r="1.2" fill="currentColor" /><circle cx="12" cy="12" r="1.2" fill="currentColor" /><circle cx="12" cy="18.5" r="1.2" fill="currentColor" /></I>;
export const Sort = (p) => <I {...p}><path d="M8 9l4-4 4 4M8 15l4 4 4-4" /></I>;
export const ZoomIn = (p) => <I {...p}><circle cx="11" cy="11" r="6.5" /><path d="M11 8.5v5M8.5 11h5M20 20l-4.2-4.2" /></I>;
export const ZoomOut = (p) => <I {...p}><circle cx="11" cy="11" r="6.5" /><path d="M8.5 11h5M20 20l-4.2-4.2" /></I>;
export const Fit = (p) => <I {...p}><path d="M4 9V5a1 1 0 011-1h4M20 9V5a1 1 0 00-1-1h-4M4 15v4a1 1 0 001 1h4M20 15v4a1 1 0 01-1 1h-4" /></I>;
export const Shield = (p) => <I {...p}><path d="M12 3l7 3v5.5c0 4.4-3 7.6-7 9.5-4-1.9-7-5.1-7-9.5V6l7-3z" /><path d="M9 12l2 2 4-4" /></I>;
export const Grid = (p) => <I {...p}><rect x="4" y="4" width="6.5" height="6.5" rx="1.4" /><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.4" /><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.4" /><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.4" /></I>;
export const Check = (p) => <I {...p}><path d="M5 12.5l4.5 4.5L19 7" /></I>;
export const Alert = (p) => <I {...p}><path d="M12 4l9 16H3L12 4z" /><path d="M12 10v4M12 17v.2" /></I>;
export const Play = (p) => <I {...p}><path d="M8 5.5l10 6.5-10 6.5v-13z" /></I>;
export const Refresh = (p) => <I {...p}><path d="M20 11a8 8 0 10-2.6 6.3M20 5v6h-6" /></I>;
export const Link = (p) => <I {...p}><path d="M10 13a5 5 0 007 0l2-2a5 5 0 00-7-7l-1 1" /><path d="M14 11a5 5 0 00-7 0l-2 2a5 5 0 007 7l1-1" /></I>;
export const Key = (p) => <I {...p}><circle cx="8" cy="12" r="4" /><path d="M12 12h9M17 12v3M20 12v2" /></I>;
export const Dot = ({ className = "w-2 h-2" }) => <svg viewBox="0 0 8 8" className={className}><circle cx="4" cy="4" r="3.2" fill="currentColor" /></svg>;

// --- entity glyphs (white, inside hexagons) ------------------------------
const glyph = { fill: "none", stroke: "#fff", strokeWidth: 1.9, strokeLinecap: "round", strokeLinejoin: "round", viewBox: "0 0 24 24" };

export const PersonGlyph = ({ className = "w-4 h-4", stroke = "#fff" }) => (
  <svg {...glyph} width={16} height={16} stroke={stroke} className={className}><circle cx="12" cy="8.5" r="2.8" /><path d="M6.5 19c.6-3.2 2.8-4.8 5.5-4.8s4.9 1.6 5.5 4.8" /></svg>
);
export const BankGlyph = ({ className = "w-4 h-4", stroke = "#fff" }) => (
  <svg {...glyph} width={16} height={16} stroke={stroke} className={className}><path d="M4 9.5L12 5l8 4.5" /><path d="M5.5 10.5h13M7 10.5V17M11 10.5V17M15 10.5V17M17.5 10.5V17M4.5 19.5h15" /></svg>
);
export const CardGlyph = ({ className = "w-4 h-4", stroke = "#fff" }) => (
  <svg {...glyph} width={16} height={16} stroke={stroke} className={className}><rect x="3.5" y="6" width="17" height="12" rx="2" /><path d="M3.5 10h17M7 14.5h3" /></svg>
);
export const DocGlyph = ({ className = "w-4 h-4", stroke = "#fff" }) => (
  <svg {...glyph} width={16} height={16} stroke={stroke} className={className}><path d="M7 4h7l3.5 3.5V20H7V4z" /><path d="M14 4v4h4M9.5 12h5M9.5 15h5" /></svg>
);
export const BuildingGlyph = ({ className = "w-4 h-4", stroke = "#fff" }) => (
  <svg {...glyph} width={16} height={16} stroke={stroke} className={className}><path d="M5 20V6.5L12 4v16M12 20h7V9.5l-7-2" /><path d="M8 9h1M8 12.5h1M8 16h1M15 12h1M15 15.5h1" /></svg>
);
