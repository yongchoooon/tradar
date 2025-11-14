const { useState, useMemo, useRef, useEffect } = React;

const GOODS_LIMIT = 10;
const RESULT_PAGE_SIZE = 20;
const RESULT_LIMIT = 200;

const cloneDeep = (value) => (value == null ? value : JSON.parse(JSON.stringify(value)));

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


function GoodsSearchPanel({ selectedGroups, onToggleGroup }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState(new Set());

  const fetchGoods = async (e) => {
    e?.preventDefault();
    const term = query.trim();
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
      setExpanded(new Set());
    } catch (err) {
      setError(err?.message || '검색 중 오류가 발생했습니다');
    } finally {
      setLoading(false);
    }
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
        <button type="submit" className="btn-primary">검색</button>
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
        <span>이미지를 선택하세요</span>
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

  return (
    <section className="search-section">
      <h2>상표 검색</h2>
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
            className="dropzone"
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

function ResultCard({ item, variant }) {
  const status = (item.status || '').trim();
  const statusClass = STATUS_MAP[status.toLowerCase()] || 'status-default';
  const simLabel = variant === 'image' ? '이미지 유사도' : '텍스트 유사도';
  const simValue = variant === 'image' ? item.image_sim : item.text_sim;
  return (
    <article className="result-card">
      <div className="result-card__thumb">
        {item.thumb_url ? (
          <img src={item.thumb_url} alt={`${item.title} 미리보기`} loading="lazy" />
        ) : (
          <div className="thumb-placeholder">이미지 없음</div>
        )}
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
          {item.doi ? (
            <a href={item.doi} className="meta-item meta-link" target="_blank" rel="noopener noreferrer">DOI 바로가기</a>
          ) : (
            <span className="meta-item">DOI 정보 없음</span>
          )}
        </div>
        <div className="result-divider" />
        <footer>
          <span>{simLabel} {simValue?.toFixed ? simValue.toFixed(3) : simValue}</span>
        </footer>
      </div>
    </article>
  );
}

function PromptBlendSelector({ label, options, value, onChange }) {
  return (
    <div className="prompt-panel__blend">
      <span className="prompt-panel__blend-label">{label}</span>
      <div className="prompt-panel__blend-options">
        {options.map((option) => {
          const isActive = value === option.value;
          return (
            <button
              key={option.value}
              type="button"
              className={`prompt-blend-button ${isActive ? 'is-active' : ''}`}
              onClick={() => onChange(option.value)}
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
        {hasVariants && (
          <p className="variants">LLM 유사어: {variants.join(', ')}</p>
        )}
      </div>
      <div className="results-section__inner">
        {visibleItems.length ? (
          <div className="results-grid">
            {visibleItems.map((item) => (
              <ResultCard key={`${variant}-top-${item.trademark_id}`} item={item} variant={variant} />
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
                <ResultCard key={`${variant}-misc-${item.trademark_id}`} item={item} variant={variant} />
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
      setResponse(data);
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
      if (targets.image && targets.text) {
        setBaseResponse(cloneDeep(data));
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

  const executeSearch = async (debug = false) => {
    if (!imageFile) {
      setPlaceholderNotice('이미지를 먼저 선택하고 검색을 실행해 주세요.');
      setError('');
      focusImageUploader();
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
  };

  const handleTextReset = () => {
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
  };

  const resetForm = () => {
    setImageFile(null);
    setTitle('');
    setPlaceholderNotice('');
  };

  return (
    <>
      <section className="hero">
        <img className="logo" src="/logo-tradar.png" alt="T-RADAR" />
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
      />
      <GoodsSearchPanel
        selectedGroups={selectedGroups}
        onToggleGroup={toggleGroup}
      />
      <div className="search-actions-row">
        <button type="button" className="secondary btn-wide" onClick={resetForm}>초기화</button>
        <button type="button" className="btn-primary btn-wide" onClick={() => executeSearch(false)}>검색</button>
        <button type="button" className="btn-debug btn-wide" onClick={() => executeSearch(true)}>검색(디버그)</button>
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
              />
              <form
                className="prompt-panel"
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
                />
                <div className="prompt-panel__content">
                  <textarea
                    id="image-rerank"
                    placeholder="추가로 설명하고 싶은 내용을 입력하세요"
                    value={imagePrompt}
                    onChange={(e) => setImagePrompt(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        handleImageRerank(false);
                      }
                    }}
                    rows={3}
                  />
                  <div className="prompt-panel__actions">
                    <button
                      type="submit"
                      className="btn-secondary"
                    >
                      이미지 재검색
                    </button>
                    <button
                      type="button"
                      className="btn-debug"
                      onClick={() => handleImageRerank(true)}
                    >
                      이미지 재검색(디버그)
                    </button>
                    <button
                      type="button"
                      className="btn-outline"
                      onClick={handleImageReset}
                      disabled={!baseResponse}
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
                variants={response.query?.variants || []}
                loading={loadingState.text}
                loadingLabel="텍스트 결과 업데이트 중..."
                page={pages.text}
                pageSize={RESULT_PAGE_SIZE}
                onPageChange={(next) => setPages((prev) => ({ ...prev, text: next }))}
              />
              <form
                className="prompt-panel"
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
                />
                <div className="prompt-panel__content">
                  <textarea
                    id="text-rerank"
                    placeholder="추가 텍스트 프롬프트를 입력하세요"
                    value={textPrompt}
                    onChange={(e) => setTextPrompt(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        handleTextRerank(false);
                      }
                    }}
                    rows={3}
                  />
                  <div className="prompt-panel__actions">
                    <button
                      type="submit"
                      className="btn-secondary"
                    >
                      텍스트 재검색
                    </button>
                    <button
                      type="button"
                      className="btn-debug"
                      onClick={() => handleTextRerank(true)}
                    >
                      텍스트 재검색(디버그)
                    </button>
                    <button
                      type="button"
                      className="btn-outline"
                      onClick={handleTextReset}
                      disabled={!baseResponse}
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
                <h3>{placeholderNotice ? '이미지 업로드가 필요합니다' : '검색을 시작해 주세요'}</h3>
                <p>
                  {placeholderNotice || '이미지와 상표명을 입력한 뒤 검색 버튼을 누르면 결과가 여기 표시됩니다.'}
                </p>
                {placeholderNotice && (
                  <button
                    type="button"
                    className="placeholder-action"
                    onClick={focusImageUploader}
                  >
                    이미지 선택하러 가기
                  </button>
                )}
              </div>
            </div>
          )}
          {loading && (
            <div className="search-overlay">
              <span>검색 중..</span>
            </div>
          )}
        </div>
      </section>
    </>
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

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
