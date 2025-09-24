const { useState, useMemo, useRef, useEffect } = React;

const GOODS_LIMIT = 10;

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

function TrademarkSearchForm({ onSearch, selectedGroups }) {
  const [imageFile, setImageFile] = useState(null);
  const [title, setTitle] = useState('');
  const fileInputRef = useRef(null);

  const selectedGroupCodes = useMemo(() => Object.keys(selectedGroups), [selectedGroups]);
  const selectedClassCodes = useMemo(() => {
    const codes = new Set();
    Object.values(selectedGroups).forEach((item) => {
      if (item.classCode) codes.add(item.classCode);
    });
    return Array.from(codes);
  }, [selectedGroups]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      const image = await fileToBase64(imageFile);
      await onSearch({
        image_b64: image,
        boxes: [],
        goods_classes: selectedClassCodes,
        group_codes: selectedGroupCodes,
        k: 20,
        text: title.trim() || null,
      });
    } catch (err) {
      console.error(err);
      alert('검색 요청 중 오류가 발생했습니다. 콘솔을 확인하세요.');
    }
  };

  const reset = () => {
    setImageFile(null);
    setTitle('');
  };

  return (
    <section className="search-section">
      <h2>상표 검색</h2>
      <form className="search-card" onSubmit={handleSubmit}>
        <div className="search-card__top">
          <label>
            상표명
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="예: 커피한잔"
            />
          </label>
          <div className="selected-summary">
            <span>선택한 유사군 코드: {selectedGroupCodes.length || 0}개</span>
            <span>포함된 류: {selectedClassCodes.join(', ') || '없음'}</span>
          </div>
        </div>
        <div className="upload-row">
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            style={{ display: 'none' }}
            onChange={(e) => setImageFile(e.target.files?.[0] || null)}
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
          <div className="actions-side">
            <button type="submit" className="btn-primary btn-fixed btn-equal">검색</button>
            <button
              type="reset"
              className="secondary btn-fixed btn-equal btn-wide"
              onClick={reset}
            >
              초기화
            </button>
          </div>
        </div>
      </form>
    </section>
  );
}

function ResultCard({ item }) {
  return (
    <article className="result-card">
      <header>
        <strong>{item.title}</strong>
        <span className={`status status-${item.status}`}>{item.status}</span>
      </header>
      <p className="result-meta">
        <span>상표ID: {item.trademark_id}</span>
        <span>출원번호: {item.app_no}</span>
        <span>분류: {item.class_codes.join(', ')}</span>
      </p>
      <footer>
        <span>이미지 유사도 {item.image_sim.toFixed(3)}</span>
        <span>텍스트 유사도 {item.text_sim.toFixed(3)}</span>
      </footer>
    </article>
  );
}

function ResultSection({ title, groups }) {
  const sections = [
    ['adjacent', '인접군'],
    ['non_adjacent', '비인접군'],
    ['registered', '등록'],
    ['refused', '거절'],
    ['others', '기타'],
  ];

  return (
    <section className="results-section">
      <h3>{title}</h3>
      {sections.map(([key, label]) => {
        const items = groups?.[key] || [];
        if (!items.length) return null;
        return (
          <div key={key} className="results-group">
            <h4>{label}</h4>
            <div className="results-grid">
              {items.map((item) => (
                <ResultCard key={`${key}-${item.trademark_id}`} item={item} />
              ))}
            </div>
          </div>
        );
      })}
    </section>
  );
}

function App() {
  const [selectedGroups, setSelectedGroups] = useState({});
  const [response, setResponse] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

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

  const search = async (payload) => {
    setLoading(true);
    setError('');
    try {
      const res = await fetch('/search/multimodal', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setResponse(data);
    } catch (err) {
      setError(err?.message || '검색 중 문제가 발생했습니다');
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <section className="hero">
        <img className="logo" src="/logo-tradar.png" alt="T-RADAR" />
        <div className="hero-text">
          <h1 className="title">T-RADAR</h1>
          <p className="subtitle">텍스트·이미지 기반 유사 상표 검색 서비스</p>
        </div>
      </section>
      <TrademarkSearchForm onSearch={search} selectedGroups={selectedGroups} />
      <GoodsSearchPanel
        selectedGroups={selectedGroups}
        onToggleGroup={toggleGroup}
      />
      <section className="search-results">
        <h2>검색 결과</h2>
        {loading && <p>검색 중입니다…</p>}
        {error && <p role="alert">{error}</p>}
        {!loading && !error && response && (
          <>
            <p className="query-summary">
              Top-{response.query?.k || 0} · 박스 {response.query?.boxes || 0}개 · 선택 류 {(response.query?.goods_classes || []).join(', ') || '없음'} · 유사군 {(response.query?.group_codes || []).join(', ') || '없음'}
            </p>
            <ResultSection title="이미지 유사 Top-K" groups={response.image_topk} />
            <ResultSection title="텍스트 유사 Top-K" groups={response.text_topk} />
          </>
        )}
      </section>
    </>
  );
}

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
