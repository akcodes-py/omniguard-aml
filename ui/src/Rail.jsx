import { Search, Plus, Flask, Filter, Info, Menu } from "./icons.jsx";

function RailBtn({ label, active, onClick, children, className = "" }) {
  return (
    <button
      onClick={onClick}
      aria-label={label}
      className={`group relative w-10 h-10 rounded-md flex items-center justify-center transition-colors ${
        active ? "text-white bg-white/10" : "text-[#7f93a8] hover:text-white hover:bg-white/[0.06]"
      } ${className}`}
    >
      {children}
      <span className="pointer-events-none absolute left-[46px] z-50 whitespace-nowrap rounded-md bg-slate-900 px-2 py-1 text-[11px] font-medium text-white opacity-0 shadow-lg transition-opacity group-hover:opacity-100">
        {label}
      </span>
    </button>
  );
}

export default function Rail({ mode, onMode, onSearch, onFilters, filtersOpen, onInfo, infoOpen, onAlerts }) {
  return (
    <div className="w-[58px] shrink-0 bg-[#0b1b2b] flex flex-col items-center py-3 z-30">
      <button
        onClick={() => onMode("genome")}
        aria-label="OmniGuard home"
        className="w-10 h-10 rounded-md flex items-center justify-center text-white hover:bg-white/[0.06] transition-colors mb-3"
      >
        <svg viewBox="0 0 24 24" className="w-[22px] h-[22px]" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round">
          <path d="M12 3v18M4.2 7.5l15.6 9M19.8 7.5l-15.6 9" />
          <circle cx="12" cy="12" r="2.1" fill="#0b1b2b" />
        </svg>
      </button>

      <div className="w-7 h-px bg-white/10 mb-3" />

      <div className="flex flex-col gap-1.5">
        <RailBtn label="Search alerts" onClick={onSearch}>
          <Search className="w-[19px] h-[19px]" />
        </RailBtn>
        <RailBtn label="New investigation" onClick={onSearch}>
          <Plus className="w-[19px] h-[19px]" />
        </RailBtn>
        <RailBtn label="Scenario Lab" active={mode === "scenario"} onClick={() => onMode("scenario")}>
          <Flask className="w-[19px] h-[19px]" />
        </RailBtn>
        <RailBtn label="Graph filters" active={filtersOpen} onClick={onFilters}>
          <Filter className="w-[18px] h-[18px]" />
        </RailBtn>
        <RailBtn label="About OmniGuard" active={infoOpen} onClick={onInfo}>
          <Info className="w-[19px] h-[19px]" />
        </RailBtn>
      </div>

      <div className="mt-auto">
        <RailBtn label="Recent alerts" onClick={onAlerts}>
          <Menu className="w-[19px] h-[19px]" />
        </RailBtn>
      </div>
    </div>
  );
}
