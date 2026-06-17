import React from 'react';
import { buildNepseAlphaChartUrl } from '../lib/nepseAlpha';
import './NepseAlphaSymbolLink.css';

interface NepseAlphaSymbolLinkProps {
  symbol: string;
  className?: string;
  children?: React.ReactNode;
  stopPropagation?: boolean;
}

const NepseAlphaSymbolLink: React.FC<NepseAlphaSymbolLinkProps> = ({
  symbol,
  className = '',
  children,
  stopPropagation = false,
}) => {
  const href = buildNepseAlphaChartUrl(symbol);
  const label = children ?? symbol;

  if (!href) {
    return <span className={className}>{label}</span>;
  }

  const handleClick = (event: React.MouseEvent<HTMLAnchorElement>) => {
    if (stopPropagation) {
      event.stopPropagation();
    }
  };

  return (
    <a
      className={`nepse-alpha-symbol-link ${className}`.trim()}
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      title={`Open ${symbol.trim()} chart on Nepse Alpha`}
      onClick={handleClick}
    >
      {label}
    </a>
  );
};

export default NepseAlphaSymbolLink;
