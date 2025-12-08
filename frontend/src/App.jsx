import React, { useState, useMemo, useRef, useEffect, useCallback } from 'react';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import {
  FiInfo,
  FiFileText,
  FiRefreshCcw,
  FiStopCircle,
  FiCheckCircle,
  FiAlertTriangle,
  FiXCircle,
  FiSearch,
  FiTerminal,
  FiPlayCircle,
} from 'react-icons/fi';
import logo from './assets/logo-tradar.png';

const GOODS_LIMIT = 10;
const RESULT_PAGE_SIZE = 18;
const RESULT_LIMIT = 200;
const SIMULATION_DEFAULT_PER_VARIANT = 5;
const SIMULATION_MAX_SELECTION = 40;
const STATIC_PUBLIC_PREFIX = '/home/work/workspace/tradar/frontend/public';

const EXAMPLE_PRESETS = {
  example1: {
    title: 'T-RADAR',
    imagePath: '/home/work/workspace/tradar/frontend/public/logo-tradar.png',
    goodsQuery: '검색',
    groups: [
      {
        classCode: '45',
        className: '법률·IP 서비스',
        groupCode: 'S120402',
        names: ['지식재산권 자문', '상표 분쟁 대응 서비스'],
      },
      {
        classCode: '35',
        className: '광고·사업관리',
        groupCode: 'S2039',
        names: ['브랜드 전략 컨설팅', '상표 데이터 분석 서비스'],
      },
      {
        classCode: '38',
        className: '통신 서비스',
        groupCode: 'S0601',
        names: ['온라인 플랫폼 제공', '데이터 전송 서비스'],
      },
      {
        classCode: '09',
        className: '과학·전자기기',
        groupCode: 'G390802',
        names: ['인공지능 소프트웨어', '검색 프로그램'],
      },
    ],
  },
  example2: {
    title: 'Hard Rock',
    imagePath: '/home/work/workspace/tradar/frontend/public/logo-hard_rock.jpg',
    goodsQuery: '맥주',
    groups: [
      {
        classCode: '32',
        className: '무알콜 음료',
        groupCode: 'G0602',
        names: ['무알콜 칵테일', '카페 음료 제조'],
      },
    ],
  },
};

const resolveStaticAssetPath = (input) => {
  if (!input) return '';
  if (input.startsWith('http://') || input.startsWith('https://')) {
    return input;
  }
  if (input.startsWith(STATIC_PUBLIC_PREFIX)) {
    const relative = input.slice(STATIC_PUBLIC_PREFIX.length);
    if (!relative) {
      return '/';
    }
    return relative.startsWith('/') ? relative : `/${relative}`;
  }
  return input.startsWith('/') ? input : `/${input}`;
};

const fetchStaticAssetFile = async (assetPath) => {
  const normalized = resolveStaticAssetPath(assetPath);
  const res = await fetch(normalized);
  if (!res.ok) {
    throw new Error(`Failed to fetch asset: ${normalized}`);
  }
  const blob = await res.blob();
  const filename = normalized.split('/').pop() || 'example.png';
  return new File([blob], filename, { type: blob.type || 'image/png' });
};

const getResultKey = (item) => (
  item?.application_number
  ?? item?.applicationNumber
  ?? item?.trademark_id
  ?? item?.app_no
  ?? item?.id
);

const buildSelectionMap = (items = [], limit = SIMULATION_DEFAULT_PER_VARIANT) => {
  const map = {};
  items.slice(0, limit).forEach((item) => {
    const key = getResultKey(item);
    if (key) {
      map[key] = item;
    }
  });
  return map;
};

const buildHighlightMap = (items = [], limit = SIMULATION_DEFAULT_PER_VARIANT) => {
  const map = {};
  items.slice(0, limit).forEach((item) => {
    const key = getResultKey(item);
    if (key) {
      map[key] = true;
    }
  });
  return map;
};

const cloneDeep = (value) => (value == null ? value : JSON.parse(JSON.stringify(value)));

const normalizeMarkdown = (value) => {
  if (!value) return '';
  return value
    .replace(/\r\n/g, '\n')
    .replace(/^([\t ]*)[·•▪◦‣⁃⦁●]\s+/gm, '$1- ')
    // 보정: 문장 바로 뒤에 오는 불릿을 명시적 목록으로 인식시키기 위해 빈 줄 삽입
    .replace(/([^\n])\n(-\s+)/g, '$1\n\n$2');
};

const IMAGE_BLEND_OPTIONS = [
  { value: 'primary_strong', label: '이미지 최우선', helper: '이미지 90% · 프롬프트 10%' },
  { value: 'primary_focus', label: '이미지 우선', helper: '이미지 70% · 프롬프트 30%' },
  { value: 'balanced', label: '균형', helper: '이미지 50% · 프롬프트 50%' },
  { value: 'prompt_focus', label: '문장 우선', helper: '이미지 30% · 프롬프트 70%' },
  { value: 'prompt_strong', label: '문장 최우선', helper: '이미지 10% · 프롬프트 90%' },
];

const TEXT_BLEND_OPTIONS = [
  { value: 'primary_strong', label: '원문 최우선', helper: '원문 90% · 프롬프트 10%' },
  { value: 'primary_focus', label: '원문 우선', helper: '원문 70% · 프롬프트 30%' },
  { value: 'balanced', label: '균형', helper: '원문 50% · 프롬프트 50%' },
  { value: 'prompt_focus', label: '프롬프트 우선', helper: '원문 30% · 프롬프트 70%' },
  { value: 'prompt_strong', label: '프롬프트 최우선', helper: '원문 10% · 프롬프트 90%' },
];

const SCORE_SEGMENTS = [
  { label: '매우 낮음', max: 17 },
  { label: '낮음', max: 34 },
  { label: '약간 낮음', max: 50 },
  { label: '약간 높음', max: 66 },
  { label: '높음', max: 83 },
  { label: '매우 높음', max: 100 },
];

const clampScore = (value) => Math.max(0, Math.min(100, Number(value) || 0));

const describeScoreBand = (value) => {
  const clamped = clampScore(value);
  if (!Number.isFinite(clamped)) return '정보 부족';
  if (clamped < 10) return '매우 낮음';
  if (clamped < 30) return '낮음';
  if (clamped < 50) return '약간 낮음';
  if (clamped < 70) return '약간 높음';
  if (clamped < 90) return '높음';
  return '매우 높음';
};

const renderScoreBar = (title, value, secondary) => {
  const safe = clampScore(value);
  const segmentIndex = SCORE_SEGMENTS.findIndex((segment) => safe <= segment.max);
  const hasSecondary = secondary && Number.isFinite(secondary.value);
  const secondaryValue = hasSecondary ? clampScore(secondary.value) : null;
  const markerLabel = secondary?.kind === 'max' ? '최댓값' : '최솟값';
  return (
    <div className="simulation-score-bar" key={title}>
      <div className="simulation-score-bar__header">
        <span className="simulation-score-bar__title">{title}</span>
      </div>
      <div className="simulation-score-bar__body">
        <div className="simulation-score-bar__track">
          {SCORE_SEGMENTS.map((segment, idx) => (
            <div
              key={segment.label}
              className={[
                'simulation-score-bar__segment',
                `simulation-score-bar__segment--${idx + 1}`,
                idx === segmentIndex ? 'is-active' : '',
              ].filter(Boolean).join(' ')}
            >
              <span>{segment.label}</span>
            </div>
          ))}
        </div>
        {hasSecondary && secondaryValue !== null && (
          <div
            className={`simulation-score-bar__marker simulation-score-bar__marker--${secondary.kind}`}
            style={{ left: `${secondaryValue}%` }}
          >
            <span className="simulation-score-bar__marker-label">
              {markerLabel} {secondaryValue.toFixed(1)}점
            </span>
            <span className="simulation-score-bar__marker-triangle" />
            <span className="simulation-score-bar__marker-line" />
          </div>
        )}
        <div
          className="simulation-score-bar__marker simulation-score-bar__marker--avg"
          style={{ left: `${safe}%` }}
        >
          <span className="simulation-score-bar__marker-label">
            평균 {safe.toFixed(1)}점
          </span>
          <span className="simulation-score-bar__marker-triangle" />
        </div>
      </div>
    </div>
  );
};

function MarkdownBlock({ text, className }) {
  const html = useMemo(() => {
    if (!text) {
      return '';
    }
    const normalized = normalizeMarkdown(text);
    const parsed = marked(normalized, { gfm: true, breaks: false });
    return DOMPurify.sanitize(parsed);
  }, [text]);

  if (!text) return null;
  const classes = ['markdown-block', 'markdown-body', className].filter(Boolean).join(' ');
  return (
    <div
      className={classes}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

function GoodsGroupList({ classItem, expanded, onToggleExpand, onToggleGroup, selectedGroups }) {
  const hasGroups = classItem.groups && classItem.groups.length > 0;
  if (!hasGroups) return null;
  return (
    <article className={`goods-class ${expanded ? 'is-open' : ''}`}>
      <header onClick={() => onToggleExpand(classItem.nc_class)}>
        <div className="goods-class__title">
          <span className="goods-class__badge">{classItem.nc_class}류</span>
          <span className="goods-class__name">{classItem.class_name}</span>
        </div>
        <button type="button" className="icon-button" aria-label="토글">
          {expanded ? '▾' : '▸'}
        </button>
      </header>
      <ul className="goods-class__groups" hidden={!expanded}>
        {classItem.groups.map((group) => {
          const checked = Boolean(selectedGroups[group.similar_group_code]);
          return (
            <li key={group.similar_group_code}>
              <label className="goods-group__row">
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={(e) => onToggleGroup({
                    checked: e.target.checked,
                    classCode: classItem.nc_class,
                    className: classItem.class_name,
                    groupCode: group.similar_group_code,
                    names: group.names,
                  })}
                />
                <span className="goods-group__code">({group.similar_group_code})</span>
                <span className="goods-group__names">{group.names.join(', ')}</span>
              </label>
            </li>
          );
        })}
      </ul>
    </article>
  );
}


function GoodsSearchPanel({ selectedGroups, onToggleGroup, preset }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState(new Set());

  const runGoodsSearch = useCallback(async (termInput, options = {}) => {
    const term = (termInput || '').trim();
    if (!term) {
      setResults([]);
      setError('');
      setExpanded(new Set());
      return;
    }
    try {
      setLoading(true);
      setError('');
      const res = await fetch(`/goods/search?q=${encodeURIComponent(term)}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const items = (data?.results || [])
        .filter((item) => Array.isArray(item.groups) && item.groups.length > 0)
        .slice(0, GOODS_LIMIT);
      setResults(items);
      if (options.expandSelected) {
        const autoExpanded = new Set();
        items.forEach((item) => {
          const hasSelected = item.groups?.some(
            (group) => selectedGroups?.[group.similar_group_code],
          );
          if (hasSelected) {
            autoExpanded.add(item.nc_class);
          }
        });
        setExpanded(autoExpanded);
      } else {
        setExpanded(new Set());
      }
    } catch (err) {
      setError(err?.message || '검색 중 오류가 발생했습니다');
    } finally {
      setLoading(false);
    }
  }, [selectedGroups]);

  const fetchGoods = async (e) => {
    e?.preventDefault();
    await runGoodsSearch(query);
  };

  const toggleExpand = (code) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(code)) {
        next.delete(code);
      } else {
        next.add(code);
      }
      return next;
    });
  };

  useEffect(() => {
    if (!preset || typeof preset.term !== 'string') {
      return;
    }
    const term = preset.term || '';
    setQuery(term);
    runGoodsSearch(term, { expandSelected: true });
  }, [preset, runGoodsSearch]);

  return (
    <section className="goods-panel">
      <h2>상품/서비스류 검색</h2>
      <form className="goods-search" onSubmit={fetchGoods}>
        <input
          type="search"
          placeholder="예: 커피, 애플리케이션, 교육"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button type="submit" className="action-button action-button--primary goods-search__submit">
          <FiSearch aria-hidden="true" />
          <span>검색</span>
        </button>
      </form>
      {error && <p role="alert" className="goods-error">{error}</p>}
      {loading && <p>검색 중입니다…</p>}
      {!loading && !error && !results.length && query.trim() && (
        <p>일치하는 분류를 찾지 못했습니다.</p>
      )}
      <div className="goods-results">
        {results.map((item) => (
          <GoodsGroupList
            key={item.nc_class}
            classItem={item}
            expanded={expanded.has(item.nc_class)}
            onToggleExpand={toggleExpand}
            onToggleGroup={onToggleGroup}
            selectedGroups={selectedGroups}
          />
        ))}
      </div>
    </section>
  );
}

function PreviewImage({ file }) {
  const url = useMemo(() => (file ? URL.createObjectURL(file) : null), [file]);
  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);
  if (!url) {
    return (
      <div className="placeholder">
        <span className="placeholder__title">이미지를 선택하세요</span>
        <small>클릭하여 파일 선택</small>
      </div>
    );
  }
  return <img src={url} alt="업로드 미리보기" />;
}

async function fileToBase64(file) {
  if (!file) return '';
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result;
      if (typeof result === 'string') {
        const base64 = result.split(',')[1] || '';
        resolve(base64);
      } else {
        resolve('');
      }
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

function TrademarkSearchForm({
  title,
  onTitleChange,
  imageFile,
  onImageFileChange,
  onSubmit,
  onReset,
  onExample,
}) {
  const fileInputRef = useRef(null);

  useEffect(() => {
    if (!imageFile && fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  }, [imageFile]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    await onSubmit?.(false);
  };

  const handleReset = (e) => {
    e.preventDefault();
    onReset?.();
  };

  const dropzoneClass = ['dropzone', imageFile ? '' : 'dropzone--empty'].filter(Boolean).join(' ');

  return (
    <section className="search-section">
      <div className="search-section__heading">
        <h2>상표 검색</h2>
        <div className="example-button-group" role="group" aria-label="예시 불러오기">
          <button type="button" className="btn-outline" onClick={() => onExample?.('example1')}>
            예시 1 : T-RADAR
          </button>
          <button type="button" className="btn-outline" onClick={() => onExample?.('example2')}>
            예시 2 : Hard Rock
          </button>
        </div>
      </div>
      <form className="search-card" onSubmit={handleSubmit} onReset={handleReset}>
        <div className="search-card__top">
          <label className="field-group">
            <span className="field-label">상표명</span>
            <input
              type="text"
              value={title}
              onChange={(e) => onTitleChange?.(e.target.value)}
              placeholder="예: 커피한잔"
            />
          </label>
        </div>
        <div className="upload-row">
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            style={{ display: 'none' }}
            onChange={(e) => onImageFileChange?.(e.target.files?.[0] || null)}
          />
          <div
            className={dropzoneClass}
            role="button"
            tabIndex={0}
            onClick={() => fileInputRef.current?.click()}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                fileInputRef.current?.click();
              }
            }}
          >
            <PreviewImage file={imageFile} />
          </div>
        </div>
      </form>
    </section>
  );
}

function ResultCard({
  item,
  variant,
  selectable = false,
  checked = false,
  onToggleSelection,
  canSelectMore = true,
  locked = false,
}) {
  const status = (item.status || '').trim();
  const statusClass = STATUS_MAP[status.toLowerCase()] || 'status-default';
  const simLabel = variant === 'image' ? '이미지 유사도' : '텍스트 유사도';
  const simValue = variant === 'image' ? item.image_sim : item.text_sim;
  const showSelector = selectable && typeof onToggleSelection === 'function';
  const disableToggle = showSelector && !checked && !canSelectMore;
  const displayChecked = checked;
  const checkboxClassNames = ['result-card__checkbox'];
  if (locked && checked) {
    checkboxClassNames.push('is-locked-checked');
  } else if (locked && !checked) {
    checkboxClassNames.push('is-locked-empty');
  }
  if (locked) {
    checkboxClassNames.push('is-locked');
  }

  const cardClass = ['result-card', displayChecked ? 'is-highlighted' : ''].filter(Boolean).join(' ');
  const handleImageClick = () => {
    if (item.doi) {
      window.open(item.doi, '_blank', 'noopener,noreferrer');
    }
  };
  return (
    <article className={cardClass}>
      <div
        className={`result-card__thumb ${item.doi ? 'is-clickable' : ''}`}
        role={item.doi ? 'button' : undefined}
        tabIndex={item.doi ? 0 : undefined}
        onClick={item.doi ? handleImageClick : undefined}
        onKeyDown={(e) => {
          if (item.doi && (e.key === 'Enter' || e.key === ' ')) {
            e.preventDefault();
            handleImageClick();
          }
        }}
        aria-label={item.doi ? `${item.title} DOI로 이동` : undefined}
      >
        <div className="result-card__thumb-inner">
          {item.thumb_url ? (
            <img src={item.thumb_url} alt={`${item.title} 미리보기`} loading="lazy" />
          ) : (
            <div className="thumb-placeholder">이미지 없음</div>
          )}
        </div>
      </div>
      <div className="result-card__body">
        <header className="result-card__header">
          <strong className="result-title" title={item.title}>{item.title}</strong>
          <span className={`status-badge ${statusClass}`}>{status || '상태 미상'}</span>
        </header>
        <div className="result-divider" />
        <div className="result-meta">
          <span className="meta-item" title={item.app_no}>출원번호 {item.app_no}</span>
          {item.class_codes?.length ? (
            <span className="meta-item" title={item.class_codes.join(', ')}>분류 {item.class_codes.join(', ')}</span>
          ) : <span className="meta-item">분류 정보 없음</span>}
        </div>
        <div className="result-divider" />
        <footer className="result-card__footer">
          <span className="result-card__sim-label">{simLabel} {simValue?.toFixed ? simValue.toFixed(3) : simValue}</span>
          {showSelector && (
            <label
              className={['result-card__select', locked ? 'result-card__select--locked' : ''].filter(Boolean).join(' ')}
              aria-label="시뮬레이션 대상 선택"
            >
              <input
                type="checkbox"
                checked={displayChecked}
                disabled={disableToggle || locked}
                className={checkboxClassNames.join(' ')}
                onChange={(e) => onToggleSelection?.(e.target.checked)}
              />
            </label>
          )}
        </footer>
      </div>
    </article>
  );
}

function PromptBlendSelector({ label, options, value, onChange, disabled = false }) {
  return (
    <div className={`prompt-panel__blend ${disabled ? 'is-disabled' : ''}`}>
      <span className="prompt-panel__blend-label">{label}</span>
      <div className="prompt-panel__blend-options">
        {options.map((option) => {
          const isActive = value === option.value;
          return (
            <button
              key={option.value}
              type="button"
              className={`prompt-blend-button ${isActive ? 'is-active' : ''}`}
              onClick={() => {
                if (!disabled) {
                  onChange(option.value);
                }
              }}
              disabled={disabled}
            >
              <span>{option.label}</span>
              <small>{option.helper}</small>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function Pagination({ current = 1, total = 1, onChange }) {
  if (total <= 1) return null;
  const safeChange = (next) => {
    if (!onChange) return;
    const clamped = Math.min(Math.max(next, 1), total);
    if (clamped !== current) {
      onChange(clamped);
    }
  };
  const pages = Array.from({ length: total }, (_, idx) => idx + 1);
  return (
    <nav className="pagination" aria-label="페이지 이동">
      <div className="pagination__controls">
        <button type="button" onClick={() => safeChange(1)} disabled={current === 1} aria-label="맨 앞으로">
          «
        </button>
        <button type="button" onClick={() => safeChange(current - 1)} disabled={current === 1} aria-label="이전">
          ‹
        </button>
      </div>
      <div className="pagination__pages" role="group" aria-label="페이지 목록">
        {pages.map((page) => (
          <button
            key={page}
            type="button"
            className={`pagination__page ${page === current ? 'is-active' : ''}`}
            onClick={() => safeChange(page)}
            aria-current={page === current ? 'page' : undefined}
          >
            {page}
          </button>
        ))}
      </div>
      <div className="pagination__controls">
        <button type="button" onClick={() => safeChange(current + 1)} disabled={current === total} aria-label="다음">
          ›
        </button>
        <button type="button" onClick={() => safeChange(total)} disabled={current === total} aria-label="맨 뒤로">
          »
        </button>
      </div>
    </nav>
  );
}

function ResultSection({
  title,
  items = [],
  misc = [],
  variant,
  variants = [],
  loading = false,
  loadingLabel,
  page = 1,
  pageSize = RESULT_PAGE_SIZE,
  onPageChange,
  selectable = false,
  selectionMap = null,
  onToggleSelection,
  totalSelected = 0,
  selectionLimit = SIMULATION_MAX_SELECTION,
  highlightMap = null,
  selectionLocked = false,
}) {
  const hasVariants = Array.isArray(variants) && variants.length > 0;
  const overlayLabel = loadingLabel || '재검색 중…';
  const totalItems = items.length;
  const totalPages = Math.max(1, Math.ceil(totalItems / pageSize));
  const safePage = Math.min(Math.max(page, 1), totalPages);
  const startIdx = (safePage - 1) * pageSize;
  const visibleItems = items.slice(startIdx, startIdx + pageSize);
  const showPagination = totalItems > pageSize && typeof onPageChange === 'function';
  const rangeLabel = totalItems
    ? `${startIdx + 1}-${Math.min(totalItems, startIdx + pageSize)} / ${totalItems}`
    : '0 / 0';

  return (
    <section className="results-section">
      <div className="results-section__header">
        <h3>{title}</h3>
        {highlightMap && Object.keys(highlightMap).length > 0 && (
          <span className="results-section__badge">가장 유사한 상위 5개 상표</span>
        )}
      </div>
      {hasVariants && (
        <div className="results-section__subheader">
          <p className="variants variants--right">LLM 유사어: {variants.join(', ')}</p>
        </div>
      )}
      <div className="results-section__inner">
        {visibleItems.length ? (
          <div className="results-grid">
            {visibleItems.map((item) => (
              <ResultCard
                key={`${variant}-top-${item.trademark_id}`}
                item={item}
                variant={variant}
                selectable={selectable}
                checked={Boolean(selectionMap && selectionMap[getResultKey(item)])}
                canSelectMore={Boolean(selectionMap && (selectionMap[getResultKey(item)] || totalSelected < selectionLimit))}
                locked={selectionLocked}
                onToggleSelection={onToggleSelection ? (checked) => onToggleSelection(item, checked) : undefined}
              />
            ))}
          </div>
        ) : (
          <p className="empty">결과가 없습니다.</p>
        )}
        {misc.length ? (
          <div className="results-misc">
            <h4>기타 (등록/공고 외)</h4>
            <div className="results-grid misc-grid">
              {misc.map((item) => (
                <ResultCard
                  key={`${variant}-misc-${item.trademark_id}`}
                  item={item}
                  variant={variant}
                selectable={selectable}
                checked={Boolean(selectionMap && selectionMap[getResultKey(item)])}
                canSelectMore={Boolean(selectionMap && (selectionMap[getResultKey(item)] || totalSelected < selectionLimit))}
                locked={selectionLocked}
                  onToggleSelection={onToggleSelection ? (checked) => onToggleSelection(item, checked) : undefined}
              />
              ))}
            </div>
          </div>
        ) : null}
        {loading && (
          <div className="results-section__overlay">
            <span>{overlayLabel}</span>
          </div>
        )}
      </div>
      {showPagination && (
        <Pagination current={safePage} total={totalPages} onChange={onPageChange} />
      )}
    </section>
  );
}

function SimulationPanel({
  hasResults,
  imageCount,
  textCount,
  totalCount,
  maxSelection,
  status,
  onRun,
  onCancel,
  canCancel = false,
  result,
  error,
  elapsedSeconds = 0,
  modelName = '',
  docked = false,
}) {
  const [focusHighRiskOnly, setFocusHighRiskOnly] = useState(false);
  const isProcessing = ['collecting', 'loading', 'cancelling'].includes(status);
  const buttonDisabled = !hasResults || !totalCount || isProcessing;
  const panelClass = [
    'simulation-panel',
    status === 'complete' ? 'is-expanded' : '',
    docked ? 'simulation-panel--dock' : '',
    'is-visible',
  ].filter(Boolean).join(' ');
  const formatElapsed = (seconds) => {
    const safeSeconds = Math.max(0, Number(seconds) || 0);
    const minutes = Math.floor(safeSeconds / 60);
    const secs = safeSeconds % 60;
    return `${minutes}분 ${secs.toString().padStart(2, '0')}초`;
  };
  const shouldShowElapsed =
    ['collecting', 'loading', 'cancelling'].includes(status)
    || (status === 'complete' && elapsedSeconds >= 0);

  const progressSteps = [
    { key: 'collecting', label: '데이터를 불러오는 중' },
    { key: 'loading', label: '시뮬레이션 진행' },
    { key: 'complete', label: '요약 완료' },
  ];
  const stepOrder = progressSteps.map((step) => step.key);
  let progressIndex = stepOrder.indexOf(status);
  if (progressIndex < 0) {
    if (status === 'cancelling') {
      progressIndex = stepOrder.indexOf('collecting');
    } else if (['error', 'cancelled'].includes(status)) {
      progressIndex = stepOrder.indexOf('loading');
    } else if (hasResults) {
      progressIndex = 0;
    }
  }
  const statusMetaMap = {
    idle: {
      title: '시뮬레이션 준비 필요',
      message: '검색 후 자동으로 상위 후보가 선택됩니다.',
      tone: 'neutral',
      icon: FiInfo,
    },
    collecting: {
      title: '데이터를 불러오는 중',
      message: 'KIPRIS 의견제출통지서와 거절결정서를 수집·정리하는 단계입니다.',
      tone: 'waiting',
      icon: FiFileText,
    },
    loading: {
      title: 'LangGraph 에이전트 실행 중',
      message: '수집된 자료를 바탕으로 에이전트 시뮬레이션이 진행 중입니다.',
      tone: 'running',
      icon: FiRefreshCcw,
    },
    cancelling: {
      title: '취소 처리 중',
      message: '백엔드 작업을 중단하고 있습니다.',
      tone: 'warning',
      icon: FiStopCircle,
    },
    complete: {
      title: '결과가 준비되었습니다',
      message: '아래 요약과 후보별 세부 정보를 확인하세요.',
      tone: 'complete',
      icon: FiCheckCircle,
    },
    error: {
      title: '시뮬레이션에 실패했습니다',
      message: '',
      tone: 'danger',
      icon: FiAlertTriangle,
    },
    cancelled: {
      title: '시뮬레이션이 취소되었습니다',
      message: '필요 시 다시 실행해 주세요.',
      tone: 'warning',
      icon: FiXCircle,
    },
  };
  const currentStatus = statusMetaMap[status] || statusMetaMap.idle;
  const statusMessage = status === 'error'
    ? (error || '잠시 후 다시 시도해 주세요.')
    : currentStatus.message;
  const statusContent = (
    <div className={`simulation-panel__status-card simulation-panel__status-card--${currentStatus.tone}`}>
      <div className="simulation-panel__status-head">
        <span
          className={`simulation-panel__status-icon ${status === 'loading' ? 'is-rotating' : ''}`}
          aria-hidden="true"
        >
          {currentStatus.icon ? React.createElement(currentStatus.icon, { 'aria-hidden': true }) : null}
        </span>
        <div>
          <p className="simulation-panel__status-title">{currentStatus.title}</p>
          <p className="simulation-panel__status-text">{statusMessage}</p>
        </div>
      </div>
      {shouldShowElapsed && (
        <span className="simulation-panel__elapsed">경과 시간 {formatElapsed(elapsedSeconds)}</span>
      )}
    </div>
  );
  const guidanceMarkdown = [
    'AI Agent가 KIPRIS 의견제출통지서·거절결정서를 참고해 충돌 위험과 등록 가능성을 추정합니다.',
    '',
    `- 이미지/텍스트 상위 5건이 기본 선택되며 최대 ${maxSelection}건까지 확장할 수 있습니다.`,
    '- “시뮬레이션 실행” 후 진행 단계와 경과 시간을 실시간으로 확인할 수 있습니다.',
    '- 완료 시 후보별 Markdown 요약과 LLM 근거, 대화 로그가 제공됩니다.',
  ].join('\n');
  const guidanceBlock = (
    <MarkdownBlock
      className="simulation-panel__instructions"
      text={guidanceMarkdown}
    />
  );
  const variantLabels = { image: '이미지', text: '텍스트' };
  const hasResultData = Boolean(result);
  const highRiskCandidates = useMemo(() => {
    if (!result?.candidates?.length) return [];
    return result.candidates.filter((item) => clampScore(item?.conflict_score) >= 70);
  }, [result]);
  const highRiskStats = useMemo(() => {
    if (!highRiskCandidates.length) return null;
    const conflictScores = highRiskCandidates.map((item) => clampScore(item?.conflict_score));
    const registerScores = highRiskCandidates.map((item) => clampScore(item?.register_score));
    const calcAverage = (scores) => (scores.length
      ? scores.reduce((sum, value) => sum + value, 0) / scores.length
      : 0);
    const maxConflict = conflictScores.reduce((acc, value) => Math.max(acc, value), conflictScores[0]);
    const minRegister = registerScores.reduce((acc, value) => Math.min(acc, value), registerScores[0]);
    return {
      count: highRiskCandidates.length,
      avgConflict: calcAverage(conflictScores),
      avgRegister: calcAverage(registerScores),
      maxConflict,
      minRegister,
    };
  }, [highRiskCandidates]);
  useEffect(() => {
    setFocusHighRiskOnly(false);
  }, [result]);
  useEffect(() => {
    if (!highRiskStats?.count && focusHighRiskOnly) {
      setFocusHighRiskOnly(false);
    }
  }, [highRiskStats, focusHighRiskOnly]);
  const riskToggleEnabled = Boolean(highRiskStats?.count);
  const activeScoreStats = focusHighRiskOnly && riskToggleEnabled ? highRiskStats : null;
  const avgConflictScore = activeScoreStats?.avgConflict ?? result?.avg_conflict_score;
  const avgRegisterScore = activeScoreStats?.avgRegister ?? result?.avg_register_score;
  const maxConflictScore = activeScoreStats?.maxConflict ?? result?.max_conflict_score;
  const minRegisterScore = activeScoreStats?.minRegister ?? result?.min_register_score;
  const resultIsStale = hasResultData && status !== 'complete';

  return (
    <aside className={panelClass} aria-label="상표 등록 가능성 시뮬레이션">
      <div className="simulation-panel__header">
        <p className="simulation-panel__tag">AI Agent</p>
        <h3>상표 등록 가능성 시뮬레이션</h3>
      </div>
      <div className="simulation-panel__scrollable">
        <div className="simulation-panel__body">
          <section className="simulation-panel__intro">
            <p className="simulation-panel__model" aria-live="polite">
              사용 모델: {modelName || '불러오는 중...'}
            </p>
            <p className="simulation-panel__description">
              {hasResults
                ? '기본 설정(이미지 5건 + 텍스트 5건)을 기준으로 최대 40건까지 위험도를 비교합니다.'
                : '검색을 먼저 실행하면 위험도가 높은 후보 10건을 자동으로 선택해줍니다.'}
            </p>
            <div className="simulation-panel__progress" aria-hidden={progressIndex < 0}>
              {progressSteps.map((step, idx) => {
                const stepClass = [
                  'simulation-panel__progress-step',
                  idx <= progressIndex ? 'is-active' : '',
                  idx < progressIndex ? 'is-complete' : '',
                ].filter(Boolean).join(' ');
                return (
                  <div key={step.key} className={stepClass}>
                    <span className="simulation-panel__progress-dot" />
                    <span className="simulation-panel__progress-label">{step.label}</span>
                  </div>
                );
              })}
            </div>
            {statusContent}
            {hasResults ? (
              <div className="simulation-panel__summary-grid">
                <div className="simulation-panel__summary-card">
                  <p>이미지 후보</p>
                  <strong>{imageCount}</strong>
                </div>
                <div className="simulation-panel__summary-card">
                  <p>텍스트 후보</p>
                  <strong>{textCount}</strong>
                </div>
                <div className="simulation-panel__summary-card">
                  <p>총 선택 수</p>
                  <strong>{totalCount} / {maxSelection}</strong>
                </div>
              </div>
            ) : guidanceBlock}
            {![ 'collecting', 'loading', 'cancelling' ].includes(status) && (
              <div className="simulation-panel__actions">
                <button
                  type="button"
                  className="action-button action-button--primary simulation-panel__button"
                  onClick={() => onRun?.(false)}
                  disabled={buttonDisabled}
                >
                  <FiPlayCircle aria-hidden="true" />
                  <span>시뮬레이션 시작</span>
                </button>
                <button
                  type="button"
                  className="action-button action-button--debug simulation-panel__button"
                  onClick={() => onRun?.(true)}
                  disabled={buttonDisabled}
                >
                  <FiTerminal aria-hidden="true" />
                  <span>시뮬레이션 디버그</span>
                </button>
              </div>
            )}
            {( ['collecting', 'loading', 'cancelling' ].includes(status) && canCancel) && (
              <button
                type="button"
                className="ghost-button simulation-panel__button"
                onClick={onCancel}
              >
                실행 취소
              </button>
            )}
          </section>
        {hasResultData ? (
          <>
            <div className="simulation-panel__result-card">
              {result && (
                <div className="simulation-panel__score-area">
                  <div className="simulation-panel__score-bars">
                    {renderScoreBar(
                      '충돌 위험도',
                      avgConflictScore,
                      Number.isFinite(maxConflictScore)
                        ? { kind: 'max', value: maxConflictScore }
                        : null,
                    )}
                    {renderScoreBar(
                      '등록 가능성',
                      avgRegisterScore,
                      Number.isFinite(minRegisterScore)
                        ? { kind: 'min', value: minRegisterScore }
                        : null,
                    )}
                  </div>
                <div className="simulation-panel__risk-row">
                  <div className="simulation-panel__risk-group">
                    <div className={`simulation-panel__risk-banner ${focusHighRiskOnly && riskToggleEnabled ? 'is-focused' : ''}`}>
                      <div className="simulation-panel__risk-count">
                        <span className="simulation-panel__risk-label">높은 위험</span>
                        <strong className="simulation-panel__risk-value">{result.high_risk}건</strong>
                      </div>
                    </div>
                    <label
                      className={`risk-average-toggle ${focusHighRiskOnly ? 'is-active' : ''} ${!riskToggleEnabled ? 'is-disabled' : ''}`.trim()}
                    >
                      <input
                        type="checkbox"
                        checked={focusHighRiskOnly}
                        onChange={(event) => setFocusHighRiskOnly(event.target.checked)}
                        disabled={!riskToggleEnabled}
                      />
                      <span className="risk-average-toggle__switch" aria-hidden="true" />
                      <span className="risk-average-toggle__label">높은 위험만 보기</span>
                    </label>
                  </div>
                </div>
              </div>
            )}
              {resultIsStale && (
                <p className="simulation-panel__status-text">
                  새로운 시뮬레이션이 진행 중입니다. 아래 내용은 직전 결과입니다.
                </p>
              )}
              <MarkdownBlock
                className="markdown-block--panel"
                text={result.overall_report || result.summary_text}
              />
            </div>
            <div className="simulation-panel__divider" />
            <h4 className="simulation-panel__section-title">후보별 상세 분석</h4>
            <ul className="simulation-panel__list">
              {result.candidates.map((item) => (
                <li key={`sim-${item.application_number}-${item.variant}`}>
                  <details className="simulation-panel__case">
                    <summary>
                      <div className="simulation-panel__case-heading">
                        <div className="simulation-panel__case-info">
                          <div className="simulation-panel__case-thumb">
                            {item.thumb_url ? (
                              <img src={item.thumb_url} alt={`${item.title} 미리보기`} loading="lazy" />
                            ) : (
                              <span className="simulation-panel__case-thumb-placeholder">이미지 없음</span>
                            )}
                          </div>
                          <div className="simulation-panel__case-details">
                            <div className="simulation-panel__case-row">
                              <span className={`simulation-panel__variant-badge simulation-panel__variant-badge--${item.variant}`}>
                                {variantLabels[item.variant] || item.variant}
                              </span>
                              <strong className="simulation-panel__case-title" title={item.title}>{item.title}</strong>
                            </div>
                            <span className="simulation-panel__list-meta">{item.application_number}</span>
                          </div>
                        </div>
                        <div className="simulation-panel__score-pills">
                          <span className="simulation-panel__score-pill is-risk">
                            <label>충돌 위험</label>
                            <strong>{item.conflict_score?.toFixed ? item.conflict_score.toFixed(1) : item.conflict_score}점</strong>
                          </span>
                          <span className="simulation-panel__score-pill is-safe">
                            <label>등록 가능</label>
                            <strong>{item.register_score?.toFixed ? item.register_score.toFixed(1) : item.register_score}점</strong>
                          </span>
                        </div>
                      </div>
                    </summary>
                    <div className="simulation-panel__case-body">
                      {item.reporter_markdown ? (
                        <MarkdownBlock
                          className="markdown-block--panel"
                          text={item.reporter_markdown}
                        />
                      ) : item.agent_summary ? (
                        <MarkdownBlock
                          className="markdown-block--panel"
                          text={item.agent_summary}
                        />
                      ) : null}
                      {item.agent_risk && (
                        <MarkdownBlock
                          className="markdown-block--panel markdown-block--accent"
                          text={item.agent_risk}
                        />
                      )}
                      {item.llm_rationale && (
                        <div className="simulation-panel__rationale">
                          <p className="simulation-panel__section-label">LLM 근거</p>
                          <MarkdownBlock
                            className="markdown-block--panel"
                            text={item.llm_rationale}
                          />
                        </div>
                      )}
                      {item.llm_factors?.length ? (
                        <div className="simulation-panel__rationale">
                          <p className="simulation-panel__section-label">참고 요소</p>
                          <ul className="simulation-panel__factor-list">
                            {item.llm_factors.slice(0, 4).map((factor, idx) => (
                              <li key={`factor-${item.application_number}-${idx}`}>{factor}</li>
                            ))}
                          </ul>
                        </div>
                      ) : null}
                      {item.transcript?.length ? (
                        <details className="simulation-panel__transcript">
                          <summary>대화 기록 (상위 4턴)</summary>
                          <ul>
                            {item.transcript.slice(0, 4).map((line, idx) => {
                              const match = line.match(/^\[(심사관|출원인|리포터)\]\s*\n?([\s\S]*)$/);
                              const speaker = match ? match[1] : '대화';
                              const content = match ? (match[2] || '').trimStart() : line;
                              const roleClassMap = {
                                심사관: 'transcript-entry--examiner',
                                출원인: 'transcript-entry--applicant',
                                리포터: 'transcript-entry--reporter',
                              };
                              const entryClass = roleClassMap[speaker] || 'transcript-entry--default';
                              return (
                                <li key={`transcript-${item.application_number}-${idx}`}>
                                  <div className={`transcript-entry ${entryClass}`}>
                                    <div className="transcript-entry__speaker">{speaker}</div>
                                    <div className="transcript-entry__bubble">
                                      <MarkdownBlock text={content} />
                                    </div>
                                  </div>
                                </li>
                              );
                            })}
                          </ul>
                        </details>
                      ) : null}
                    </div>
                  </details>
                </li>
              ))}
            </ul>
          </>
        ) : status === 'complete' ? (
          <p className="simulation-panel__placeholder">결과를 불러오는 중입니다.</p>
        ) : null}
        </div>
      </div>
    </aside>
  );
}

function DebugPanel({ debug }) {
  if (!debug) return null;

  const tablesTop = [
    { key: 'image_dino', title: '이미지 후보 · DINO', rows: debug.image_dino },
    { key: 'image_metaclip', title: '이미지 후보 · Metaclip2', rows: debug.image_metaclip },
    { key: 'text_metaclip', title: '텍스트 후보 · Metaclip2', rows: debug.text_metaclip },
    { key: 'text_bm25', title: '텍스트 후보 · BM25', rows: debug.text_bm25 },
  ];
  const tablesBottom = [
    {
      key: 'image_blended',
      title: '최종 이미지 · 블렌딩 순위',
      rows: debug.image_blended,
      columns: [
        { key: 'rank', label: '순위', align: 'right' },
        { key: 'application_number', label: '출원번호', align: 'left' },
        { key: 'dino', label: 'DINO', align: 'right', digits: 4 },
        { key: 'metaclip', label: 'Metaclip2', align: 'right', digits: 4 },
        { key: 'blended', label: '평균', align: 'right', digits: 4 },
      ],
    },
    {
      key: 'text_ranked',
      title: '최종 텍스트 · Metaclip2 순위',
      rows: debug.text_ranked,
    },
  ];

  const hasAny = [...tablesTop, ...tablesBottom].some(
    (table) => Array.isArray(table.rows) && table.rows.length > 0,
  );
  const hasMessages = Array.isArray(debug.messages) && debug.messages.length > 0;
  if (!hasAny && !hasMessages) return null;

  const renderTable = (table) => {
    if (!Array.isArray(table.rows) || !table.rows.length) return null;
    const columns = table.columns || [
      { key: 'rank', label: '순위', align: 'right' },
      { key: 'application_number', label: '출원번호', align: 'left' },
      { key: 'score', label: '스코어', align: 'right', digits: 4 },
    ];
    return (
      <div className="debug-table" key={table.key}>
        <header>{table.title}</header>
        <table>
          <thead>
            <tr>
              {columns.map((col) => (
                <th key={col.key} scope="col" style={{ textAlign: col.align || 'left' }}>
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row) => (
              <tr key={`${table.key}-${row.application_number}-${row.rank}`}>
                {columns.map((col) => {
                  const raw = row[col.key];
                  let value = raw;
                  if (typeof raw === 'number' && col.digits != null) {
                    value = raw.toFixed(col.digits);
                  }
                  return (
                    <td key={`${table.key}-${row.application_number}-${row.rank}-${col.key}`} style={{ textAlign: col.align || 'left' }}>
                      {value}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  };

  return (
    <section className="debug-panel">
      <h3>디버그 정보</h3>
      <p className="debug-subtitle">각 스코어 후보 전체와 최종 재랭킹 결과입니다.</p>
      <div className="debug-grid debug-grid--top">
        {tablesTop.map(renderTable)}
      </div>
      <div className="debug-grid debug-grid--bottom">
        {tablesBottom.map(renderTable)}
      </div>
      {hasMessages && (
        <div className="debug-messages">
          <h4>추가 메시지</h4>
          <ul>
            {debug.messages.map((msg, idx) => (
              <li key={`debug-message-${idx}`}>{msg}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function App() {
  const [selectedGroups, setSelectedGroups] = useState({});
  const [response, setResponse] = useState(null);
  const [baseResponse, setBaseResponse] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [placeholderNotice, setPlaceholderNotice] = useState('');
  const [imageFile, setImageFile] = useState(null);
  const [title, setTitle] = useState('');
  const [imagePrompt, setImagePrompt] = useState('');
  const [textPrompt, setTextPrompt] = useState('');
  const [imageBlendMode, setImageBlendMode] = useState('balanced');
  const [textBlendMode, setTextBlendMode] = useState('balanced');
  const [lastImageBase64, setLastImageBase64] = useState('');
  const [lastSearchText, setLastSearchText] = useState('');
  const [loadingState, setLoadingState] = useState({ image: false, text: false });
  const [pages, setPages] = useState({ image: 1, text: 1 });
  const [useLlmVariants, setUseLlmVariants] = useState(false);
  const [simulationSelection, setSimulationSelection] = useState({ image: {}, text: {} });
  const [simulationDefaults, setSimulationDefaults] = useState({ image: {}, text: {} });
  const [simulationStatus, setSimulationStatus] = useState('idle');
  const [simulationResult, setSimulationResult] = useState(null);
  const [simulationJobId, setSimulationJobId] = useState(null);
  const [simulationError, setSimulationError] = useState('');
  const [simulationStartTime, setSimulationStartTime] = useState(null);
  const [simulationElapsed, setSimulationElapsed] = useState(0);
  const [simulationModel, setSimulationModel] = useState('');
  const [goodsPreset, setGoodsPreset] = useState({ term: '', nonce: 0 });
  const simulationEventRef = useRef(null);
  const baseVariants = baseResponse?.query?.variants;
  const textDisplayVariants = (baseVariants && baseVariants.length)
    ? baseVariants
    : (response?.query?.variants || []);
  const simulationLocked = ['collecting', 'loading', 'cancelling'].includes(simulationStatus);

  useEffect(() => {
    let ignore = false;
    const fetchConfig = async () => {
      try {
        const res = await fetch('/simulation/config');
        if (!res.ok) {
          throw new Error('failed');
        }
        const data = await res.json();
        if (!ignore) {
          setSimulationModel(data?.model_name || '');
        }
      } catch (err) {
        if (!ignore) {
          setSimulationModel('');
        }
      }
    };
    fetchConfig();
    return () => {
      ignore = true;
    };
  }, []);

  useEffect(() => {
    const runningStatuses = ['collecting', 'loading'];
    const finishedStatuses = ['complete', 'error', 'cancelled'];
    let timer = null;

    if (runningStatuses.includes(simulationStatus)) {
      const baseStart = simulationStartTime ?? Date.now();
      if (simulationStartTime === null) {
        setSimulationStartTime(baseStart);
        setSimulationElapsed(0);
      } else {
        setSimulationElapsed(Math.floor((Date.now() - baseStart) / 1000));
      }
      timer = window.setInterval(() => {
        setSimulationElapsed(Math.floor((Date.now() - (simulationStartTime ?? baseStart)) / 1000));
      }, 1000);
    } else if (simulationStartTime !== null && finishedStatuses.includes(simulationStatus)) {
      setSimulationElapsed(Math.floor((Date.now() - simulationStartTime) / 1000));
      setSimulationStartTime(null);
    }

    return () => {
      if (timer) {
        window.clearInterval(timer);
      }
    };
  }, [simulationStatus, simulationStartTime]);

  const toggleGroup = ({ checked, classCode, className, groupCode, names }) => {
    setSelectedGroups((prev) => {
      const next = { ...prev };
      if (checked) {
        next[groupCode] = { classCode, className, groupCode, names };
      } else {
        delete next[groupCode];
      }
      return next;
    });
  };

  const selectedGroupCodes = useMemo(() => Object.keys(selectedGroups), [selectedGroups]);
  const selectedClassCodes = useMemo(() => {
    const codes = new Set();
    Object.values(selectedGroups).forEach((item) => {
      if (item.classCode) codes.add(item.classCode);
    });
    return Array.from(codes);
  }, [selectedGroups]);

  const resetSimulationProgress = () => {
    setSimulationStatus('idle');
    setSimulationResult(null);
    setSimulationJobId(null);
    setSimulationError('');
    setSimulationStartTime(null);
    setSimulationElapsed(0);
    closeSimulationStream();
  };

  const search = async (payload, targets = { image: true, text: true }) => {
    setLoading(true);
    setError('');
    setLoadingState({
      image: Boolean(targets.image),
      text: Boolean(targets.text),
    });
    try {
      const res = await fetch('/search/multimodal', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setResponse((prev) => {
        if (!prev) {
          return data;
        }
        const next = { ...data };
        if (!targets.image) {
          next.image_top = prev.image_top;
          next.image_misc = prev.image_misc;
        }
        if (!targets.text) {
          next.text_top = prev.text_top;
          next.text_misc = prev.text_misc;
        }
        return next;
      });
      setPages((prev) => ({
        image: targets.image ? 1 : prev.image,
        text: targets.text ? 1 : prev.text,
      }));
      if (payload.image_b64) {
        setLastImageBase64(payload.image_b64);
      }
      if (typeof data?.query?.text === 'string') {
        setLastSearchText(data.query.text);
      }
      if (targets.image || targets.text) {
        setSimulationSelection((prev) => {
          const next = { ...prev };
          if (targets.image) {
            next.image = buildSelectionMap(data.image_top || []);
          }
          if (targets.text) {
            next.text = buildSelectionMap(data.text_top || []);
          }
          return next;
        });
        setSimulationDefaults((prev) => {
          const next = { ...prev };
          if (targets.image) {
            next.image = buildHighlightMap(data.image_top || []);
          }
          if (targets.text) {
            next.text = buildHighlightMap(data.text_top || []);
          }
          return next;
        });
      }
      if (targets.image && targets.text) {
        setBaseResponse(cloneDeep(data));
        resetSimulationProgress();
      }
      setPlaceholderNotice('');
    } catch (err) {
      setError(err?.message || '검색 중 문제가 발생했습니다');
    } finally {
      setLoading(false);
      setLoadingState({ image: false, text: false });
    }
  };

  const handleImageFileUpdate = (file) => {
    setImageFile(file);
    if (file) {
      setPlaceholderNotice('');
    }
  };

  const focusImageUploader = () => {
    const dropzone = document.querySelector('.dropzone');
    if (!dropzone) return;
    dropzone.classList.add('dropzone--pulse');
    dropzone.scrollIntoView({ behavior: 'smooth', block: 'center' });
    window.setTimeout(() => dropzone.classList.remove('dropzone--pulse'), 1200);
  };

  const focusGoodsPanel = () => {
    const panel = document.querySelector('.goods-panel');
    if (!panel) return;
    panel.classList.add('goods-panel--pulse');
    panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
    window.setTimeout(() => panel.classList.remove('goods-panel--pulse'), 1200);
  };

  const handleExampleLoad = async (key) => {
    const config = EXAMPLE_PRESETS[key];
    if (!config || loading) {
      return;
    }
    try {
      setError('');
      const file = await fetchStaticAssetFile(config.imagePath);
      const groupMap = {};
      (config.groups || []).forEach((group) => {
        if (!group?.groupCode) {
          return;
        }
        groupMap[group.groupCode] = {
          classCode: group.classCode,
          className: group.className,
          groupCode: group.groupCode,
          names: group.names || [],
        };
      });
      setTitle(config.title);
      setGoodsPreset({ term: config.goodsQuery || '', nonce: Date.now() });
      setSelectedGroups(groupMap);
      handleImageFileUpdate(file);
    } catch (err) {
      console.error('Example load failed', err);
      setError('예제 불러오기 중 오류가 발생했습니다.');
    }
  };

  const selectedImageCount = Object.keys(simulationSelection.image || {}).length;
  const selectedTextCount = Object.keys(simulationSelection.text || {}).length;
  const totalSimulationSelected = selectedImageCount + selectedTextCount;

  const buildSimulationSelections = () => {
    const mapItems = (items = {}, variant) => Object.values(items || {}).map((item) => ({
      application_number: item.app_no,
      title: item.title,
      variant,
      image_sim: item.image_sim,
      text_sim: item.text_sim,
      status: item.status,
      class_codes: item.class_codes || [],
      image_path: item.image_path || null,
      thumb_url: item.thumb_url || null,
      goods_services: item.goods_services || null,
    }));
    const images = mapItems(simulationSelection.image, 'image');
    const texts = mapItems(simulationSelection.text, 'text');
    return [...images, ...texts];
  };

  const buildSelectedGoodsNames = () => {
    const rows = [];
    Object.values(selectedGroups || {}).forEach((entry) => {
      if (!entry || !Array.isArray(entry.names) || entry.names.length === 0) {
        return;
      }
      const cleanedNames = entry.names
        .map((name) => (typeof name === 'string' ? name.trim() : ''))
        .filter(Boolean);
      if (!cleanedNames.length) {
        return;
      }
      const prefix = entry.groupCode ? `(${entry.groupCode}) ` : '';
      rows.push(`${prefix}${cleanedNames.join(', ')}`);
    });
    return rows;
  };

  const closeSimulationStream = () => {
    if (simulationEventRef.current) {
      simulationEventRef.current.close();
      simulationEventRef.current = null;
    }
  };

  const startSimulationStream = (jobId) => {
    closeSimulationStream();
    const source = new EventSource(`/simulation/stream/${jobId}`);
    simulationEventRef.current = source;
    source.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data || '{}');
        const status = (data.status || '').toLowerCase();
        if (status === 'pending' || status === 'queued') {
          setSimulationStatus('collecting');
        } else if (status === 'collecting') {
          setSimulationStatus('collecting');
        } else if (status === 'simulating' || status === 'running') {
          setSimulationStatus('loading');
      } else if (status === 'complete' && data.result) {
          setSimulationStatus('complete');
          setSimulationResult(data.result);
          setSimulationJobId(null);
          setSimulationError('');
          closeSimulationStream();
        } else if (status === 'failed') {
          setSimulationStatus('error');
          setSimulationError(data.error || '시뮬레이션에 실패했습니다.');
          setSimulationJobId(null);
          closeSimulationStream();
        } else if (status === 'cancelled') {
          setSimulationStatus('cancelled');
          setSimulationResult((prev) => data.result || prev || null);
          setSimulationJobId(null);
          setSimulationError('사용자가 시뮬레이션을 취소했습니다.');
          closeSimulationStream();
        } else if (status === 'not_found') {
          setSimulationStatus('error');
          setSimulationError('작업을 찾을 수 없습니다.');
          setSimulationJobId(null);
          closeSimulationStream();
        }
      } catch (err) {
        console.error(err);
        setSimulationStatus('error');
        setSimulationError('상태 스트림 처리 중 오류가 발생했습니다.');
        setSimulationJobId(null);
        closeSimulationStream();
      }
    };
    source.onerror = () => {
      setSimulationStatus('error');
      setSimulationError('스트림 연결이 종료되었습니다.');
      setSimulationJobId(null);
      closeSimulationStream();
    };
  };

  const toggleSimulationSelection = (variant, item, checked) => {
    if (simulationLocked) {
      return;
    }
    const key = getResultKey(item);
    if (!key) return;
    setSimulationSelection((prev) => {
      const nextVariantMap = { ...(prev[variant] || {}) };
      const otherVariantMap = prev[variant === 'image' ? 'text' : 'image'] || {};
      if (checked) {
        if (!nextVariantMap[key]) {
          const total = Object.keys(nextVariantMap).length + Object.keys(otherVariantMap).length;
          if (total >= SIMULATION_MAX_SELECTION) {
            alert(`시뮬레이션에 포함할 상표는 최대 ${SIMULATION_MAX_SELECTION}개까지 가능합니다.`);
            return prev;
          }
          nextVariantMap[key] = item;
        }
      } else if (nextVariantMap[key]) {
        delete nextVariantMap[key];
      }
      const next = {
        ...prev,
        [variant]: nextVariantMap,
      };
      return next;
    });
  };

  const handleSimulationRun = async (debug = false) => {
    if (!response) {
      alert('먼저 검색을 실행해 주세요.');
      return;
    }
    if (!totalSimulationSelected) {
      alert('시뮬레이션에 포함할 상표를 선택해 주세요.');
      return;
    }
    try {
      closeSimulationStream();
      setSimulationStatus('collecting');
      setSimulationError('');
      setSimulationJobId(null);
      setSimulationStartTime(Date.now());
      setSimulationElapsed(0);
      const payload = {
        selections: buildSimulationSelections(),
        debug,
        query_title: (response?.query?.text ?? title ?? '').trim() || null,
        user_goods_classes: response?.query?.goods_classes || [],
        user_group_codes: response?.query?.group_codes || [],
        user_goods_names: buildSelectedGoodsNames(),
        user_image_b64: lastImageBase64 || null,
        user_image_mime: imageFile?.type || null,
      };
      const res = await fetch('/simulation/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const data = await res.json();
      if (!data?.job_id) {
        throw new Error('작업 ID를 받지 못했습니다.');
      }
      setSimulationJobId(data.job_id);
      startSimulationStream(data.job_id);
    } catch (err) {
      console.error(err);
      setSimulationStatus('error');
      setSimulationError('시뮬레이션 실행 중 오류가 발생했습니다.');
    }
  };

  const handleSimulationCancel = async () => {
    if (!simulationJobId) {
      return;
    }
    try {
      setSimulationStatus('cancelling');
      const res = await fetch(`/simulation/cancel/${simulationJobId}`, {
        method: 'POST',
      });
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
    } catch (err) {
      console.error(err);
      setSimulationError('시뮬레이션 취소 중 오류가 발생했습니다.');
    }
  };

  useEffect(() => () => closeSimulationStream(), []);

  const executeSearch = async (debug = false) => {
    if (!imageFile) {
      setPlaceholderNotice('이미지를 먼저 선택하고 검색을 실행해 주세요.');
      setError('');
      focusImageUploader();
      return;
    }
    if (selectedGroupCodes.length === 0) {
      setPlaceholderNotice('상품/서비스류를 선택해 주세요.');
      focusGoodsPanel();
      return;
    }
    try {
      const image = await fileToBase64(imageFile);
      await search({
        image_b64: image,
        goods_classes: selectedClassCodes,
        group_codes: selectedGroupCodes,
        k: RESULT_LIMIT,
        text: title.trim() || null,
        debug,
        image_prompt: null,
        image_prompt_mode: imageBlendMode,
        text_prompt: null,
        text_prompt_mode: textBlendMode,
        variants: null,
        use_llm_variants: useLlmVariants,
      }, { image: true, text: true });
    } catch (err) {
      console.error(err);
      alert('검색 요청 중 오류가 발생했습니다. 콘솔을 확인하세요.');
    }
  };

  const handleImageRerank = async (debug = false) => {
    if (simulationLocked) {
      return;
    }
    if (!lastImageBase64) {
      alert('먼저 이미지 검색을 실행해주세요.');
      return;
    }
    const baseText = (response?.query?.text ?? lastSearchText ?? title).trim();
    const currentVariants = response?.query?.variants || null;
    await search({
      image_b64: lastImageBase64,
      goods_classes: selectedClassCodes,
      group_codes: selectedGroupCodes,
      k: response?.query?.k || RESULT_LIMIT,
      text: baseText || null,
      debug,
      image_prompt: imagePrompt.trim() || null,
      image_prompt_mode: imageBlendMode,
      text_prompt: null,
      text_prompt_mode: textBlendMode,
      variants: currentVariants,
    }, { image: true, text: false });
  };

  const handleTextRerank = async (debug = false) => {
    if (simulationLocked) {
      return;
    }
    if (!lastImageBase64) {
      alert('먼저 검색을 실행해주세요.');
      return;
    }
    const baseText = (response?.query?.text ?? lastSearchText ?? title).trim();
    const currentVariants = response?.query?.variants || null;
    await search({
      image_b64: lastImageBase64,
      goods_classes: selectedClassCodes,
      group_codes: selectedGroupCodes,
      k: response?.query?.k || RESULT_LIMIT,
      text: baseText || null,
      debug,
      image_prompt: null,
      image_prompt_mode: imageBlendMode,
      text_prompt: textPrompt.trim() || null,
      text_prompt_mode: textBlendMode,
      variants: currentVariants,
    }, { image: false, text: true });
  };

  const buildResetDebug = (prevDebug, baseDebug, message, fields) => {
    if (!prevDebug && !baseDebug) {
      return undefined;
    }
    const nextDebug = prevDebug ? cloneDeep(prevDebug) : {};
    if (baseDebug) {
      fields.forEach((field) => {
        if (field in baseDebug) {
          nextDebug[field] = cloneDeep(baseDebug[field]);
        }
      });
    }
    nextDebug.messages = [...(nextDebug.messages ?? []), message];
    return nextDebug;
  };

  const handleImageReset = () => {
    if (simulationLocked) {
      return;
    }
    if (!baseResponse || !response) {
      return;
    }
    const baseClone = cloneDeep(baseResponse);
    setResponse((prev) => {
      if (!prev) {
        return cloneDeep(baseClone);
      }
      return {
        ...prev,
        image_top: cloneDeep(baseClone.image_top) || [],
        image_misc: cloneDeep(baseClone.image_misc) || [],
        debug: buildResetDebug(
          prev.debug,
          baseClone.debug,
          '이미지 결과를 초기 상태로 복원했습니다.',
          ['image_dino', 'image_metaclip', 'image_blended'],
        ),
      };
    });
    setImagePrompt('');
    setImageBlendMode('balanced');
    setLoading(false);
    setLoadingState({ image: false, text: false });
    setPages((prev) => ({ ...prev, image: 1 }));
    setSimulationSelection((prev) => ({
      ...prev,
      image: buildSelectionMap(baseClone.image_top || []),
    }));
    setSimulationDefaults((prev) => ({
      ...prev,
      image: buildHighlightMap(baseClone.image_top || []),
    }));
  };

  const handleTextReset = () => {
    if (simulationLocked) {
      return;
    }
    if (!baseResponse || !response) {
      return;
    }
    const baseClone = cloneDeep(baseResponse);
    setResponse((prev) => {
      if (!prev) {
        return cloneDeep(baseClone);
      }
      return {
        ...prev,
        text_top: cloneDeep(baseClone.text_top) || [],
        text_misc: cloneDeep(baseClone.text_misc) || [],
        debug: buildResetDebug(
          prev.debug,
          baseClone.debug,
          '텍스트 결과를 초기 상태로 복원했습니다.',
          ['text_metaclip', 'text_bm25', 'text_ranked'],
        ),
      };
    });
    setTextPrompt('');
    setTextBlendMode('balanced');
    setLoading(false);
    setLoadingState({ image: false, text: false });
    setPages((prev) => ({ ...prev, text: 1 }));
    setSimulationSelection((prev) => ({
      ...prev,
      text: buildSelectionMap(baseClone.text_top || []),
    }));
    setSimulationDefaults((prev) => ({
      ...prev,
      text: buildHighlightMap(baseClone.text_top || []),
    }));
  };

  const resetForm = () => {
    setImageFile(null);
    setTitle('');
    setPlaceholderNotice('');
  };

  return (
    <div className="app-shell">
      <div className="search-column">
      <section className="hero">
        <img className="logo" src={logo} alt="T-RADAR" />
        <div className="hero-text">
          <div className="hero-heading">
            <h1 className="title">T-RADAR</h1>
            <a
              className="github-link hero-github"
              href="https://github.com/yongchoooon/tradar"
              target="_blank"
              rel="noopener noreferrer"
              aria-label="GitHub 저장소"
              title="GitHub 저장소"
            >
              <span className="github-link__icon">⭐</span>
              <span className="github-link__label">GitHub</span>
            </a>
          </div>
          <p className="subtitle">텍스트·이미지 기반 유사 상표 검색 서비스</p>
        </div>
      </section>
      <TrademarkSearchForm
        title={title}
        onTitleChange={setTitle}
        imageFile={imageFile}
        onImageFileChange={handleImageFileUpdate}
        onSubmit={executeSearch}
        onReset={resetForm}
        onExample={handleExampleLoad}
      />
      <GoodsSearchPanel
        selectedGroups={selectedGroups}
        onToggleGroup={toggleGroup}
        preset={goodsPreset}
      />
      <div className="search-actions-row">
        <button type="button" className="secondary btn-wide" onClick={resetForm}>초기화</button>
        <div className="search-actions">
          <button
            type="button"
            className="action-button action-button--primary"
            onClick={() => executeSearch(false)}
          >
            <FiSearch aria-hidden="true" />
            <span>일반 검색</span>
          </button>
          <button
            type="button"
            className="action-button action-button--debug"
            onClick={() => executeSearch(true)}
          >
            <FiTerminal aria-hidden="true" />
            <span>디버그 검색</span>
          </button>
        </div>
        <label className="llm-toggle" aria-label="LLM 유사어 사용 여부">
          <input
            id="llm-variants-checkbox"
            type="checkbox"
            checked={useLlmVariants}
            onChange={(e) => setUseLlmVariants(e.target.checked)}
          />
          <span>LLM 유사어</span>
        </label>
      </div>
      <section className="search-results">
        <h2>검색 결과</h2>
        {error && <p role="alert">{error}</p>}
        <div className="search-results__body">
          <div className="results-main">
            {response ? (
              <>
              <p className="query-summary">
                Top-{response.query?.k || 0} · 상표명 {response.query?.text || '미입력'} · 선택 류 {(response.query?.goods_classes || []).join(', ') || '없음'} · 유사군 {(response.query?.group_codes || []).join(', ') || '없음'}
              </p>
              <ResultSection
                title={`이미지 후보 (${(response.image_top || []).length}건)`}
                items={response.image_top || []}
                misc={response.image_misc || []}
                variant="image"
                loading={loadingState.image}
                loadingLabel="이미지 결과 업데이트 중..."
                page={pages.image}
                pageSize={RESULT_PAGE_SIZE}
                onPageChange={(next) => setPages((prev) => ({ ...prev, image: next }))}
                selectable
                selectionMap={simulationSelection.image}
                onToggleSelection={(item, checked) => toggleSimulationSelection('image', item, checked)}
                totalSelected={totalSimulationSelected}
                selectionLimit={SIMULATION_MAX_SELECTION}
                highlightMap={simulationDefaults.image}
                selectionLocked={simulationLocked}
              />
              <form
                className={`prompt-panel ${simulationLocked ? 'prompt-panel--disabled' : ''}`}
                onSubmit={(e) => {
                  e.preventDefault();
                  handleImageRerank(false);
                }}
              >
                <label className="prompt-panel__label" htmlFor="image-rerank">이미지 재검색 프롬프트</label>
                <PromptBlendSelector
                  label="이미지 반영 비율"
                  options={IMAGE_BLEND_OPTIONS}
                  value={imageBlendMode}
                  onChange={setImageBlendMode}
                  disabled={simulationLocked}
                />
                <div className="prompt-panel__content">
                  <textarea
                    id="image-rerank"
                    placeholder="추가로 설명하고 싶은 내용을 입력하세요"
                    value={imagePrompt}
                    onChange={(e) => setImagePrompt(e.target.value)}
                    onKeyDown={(e) => {
                      if (simulationLocked) {
                        return;
                      }
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        handleImageRerank(false);
                      }
                    }}
                    rows={3}
                    disabled={simulationLocked}
                  />
                  <div className="prompt-panel__actions">
                    <button
                      type="submit"
                      className="btn-secondary"
                      disabled={simulationLocked}
                    >
                      이미지 재검색
                    </button>
                    <button
                      type="button"
                      className="btn-debug"
                      onClick={() => handleImageRerank(true)}
                      disabled={simulationLocked}
                    >
                      이미지 재검색(디버그)
                    </button>
                    <button
                      type="button"
                      className="btn-outline"
                      onClick={handleImageReset}
                      disabled={!baseResponse || simulationLocked}
                    >
                      원래 이미지 결과
                    </button>
                  </div>
                </div>
              </form>
              <ResultSection
                title={`텍스트 후보 (${(response.text_top || []).length}건)`}
                items={response.text_top || []}
                misc={response.text_misc || []}
                variant="text"
                variants={textDisplayVariants}
                loading={loadingState.text}
                loadingLabel="텍스트 결과 업데이트 중..."
                page={pages.text}
                pageSize={RESULT_PAGE_SIZE}
                onPageChange={(next) => setPages((prev) => ({ ...prev, text: next }))}
                selectable
                selectionMap={simulationSelection.text}
                onToggleSelection={(item, checked) => toggleSimulationSelection('text', item, checked)}
                totalSelected={totalSimulationSelected}
                selectionLimit={SIMULATION_MAX_SELECTION}
                highlightMap={simulationDefaults.text}
                selectionLocked={simulationLocked}
              />
              <form
                className={`prompt-panel ${simulationLocked ? 'prompt-panel--disabled' : ''}`}
                onSubmit={(e) => {
                  e.preventDefault();
                  handleTextRerank(false);
                }}
              >
                <label className="prompt-panel__label" htmlFor="text-rerank">텍스트 재검색 프롬프트</label>
                <PromptBlendSelector
                  label="텍스트 반영 비율"
                  options={TEXT_BLEND_OPTIONS}
                  value={textBlendMode}
                  onChange={setTextBlendMode}
                  disabled={simulationLocked}
                />
                <div className="prompt-panel__content">
                  <textarea
                    id="text-rerank"
                    placeholder="추가 텍스트 프롬프트를 입력하세요"
                    value={textPrompt}
                    onChange={(e) => setTextPrompt(e.target.value)}
                    onKeyDown={(e) => {
                      if (simulationLocked) {
                        return;
                      }
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        handleTextRerank(false);
                      }
                    }}
                    rows={3}
                    disabled={simulationLocked}
                  />
                  <div className="prompt-panel__actions">
                    <button
                      type="submit"
                      className="btn-secondary"
                      disabled={simulationLocked}
                    >
                      텍스트 재검색
                    </button>
                    <button
                      type="button"
                      className="btn-debug"
                      onClick={() => handleTextRerank(true)}
                      disabled={simulationLocked}
                    >
                      텍스트 재검색(디버그)
                    </button>
                    <button
                      type="button"
                      className="btn-outline"
                      onClick={handleTextReset}
                      disabled={!baseResponse || simulationLocked}
                    >
                      원래 텍스트 결과
                    </button>
                  </div>
                </div>
              </form>
              <DebugPanel debug={response.debug} />
              </>
            ) : (
              <div className="search-placeholder">
              <div className={`search-placeholder__card ${placeholderNotice ? 'is-alert' : ''}`}>
                <h3>
                  {placeholderNotice === '상품/서비스류를 선택해 주세요.'
                    ? '상품/서비스류 선택이 필요합니다'
                    : placeholderNotice ? '이미지 업로드가 필요합니다' : '검색을 시작해 주세요'}
                </h3>
                <p>
                  {placeholderNotice
                    || '이미지와 상표명을 입력한 뒤 검색 버튼을 누르면 결과가 여기 표시됩니다.'}
                </p>
                {placeholderNotice && (
                  <button
                    type="button"
                    className="placeholder-action"
                    onClick={
                      placeholderNotice === '상품/서비스류를 선택해 주세요.'
                        ? focusGoodsPanel
                        : focusImageUploader
                    }
                  >
                    {placeholderNotice === '상품/서비스류를 선택해 주세요.'
                      ? '상품/서비스류 선택하러 가기'
                      : '이미지 선택하러 가기'}
                  </button>
                )}
              </div>
              </div>
            )}
          </div>
          {loading && (
            <div className="search-overlay">
              <span>검색 중..</span>
            </div>
          )}
        </div>
      </section>
      </div>
      <div className="simulation-column">
        <SimulationPanel
          hasResults={Boolean(response)}
          imageCount={selectedImageCount}
          textCount={selectedTextCount}
          totalCount={totalSimulationSelected}
          maxSelection={SIMULATION_MAX_SELECTION}
          status={simulationStatus}
          onRun={handleSimulationRun}
          onCancel={handleSimulationCancel}
          canCancel={Boolean(
            simulationJobId && ['collecting', 'loading', 'cancelling'].includes(simulationStatus)
          )}
          result={simulationResult}
          error={simulationError}
          elapsedSeconds={simulationElapsed}
          modelName={simulationModel}
          docked
        />
      </div>
    </div>
  );
}

const STATUS_MAP = {
  '등록': 'status-registered',
  'registered': 'status-registered',
  '공고': 'status-notice',
  'publication': 'status-notice',
  '공지': 'status-notice',
  '거절': 'status-refused',
  'refused': 'status-refused',
  '출원': 'status-pending',
  'pending': 'status-pending',
  '심사중': 'status-pending',
};

export default App;
