const { useState, useMemo, useRef } = React;

function ResultCard({ item, index }) {
  return (
    <article className="result-card">
      <header>
        <span className="badge">#{index + 1}</span>
        <strong>Trademark ID</strong>
      </header>
      <h3>{item.trademark_id}</h3>
      <footer>
        <small>Score</small>
        <strong>{item.score.toFixed(3)}</strong>
      </footer>
    </article>
  );
}

function ResultsList({ results, loading, error }) {
  if (loading) return <p>검색 중입니다… ⏳</p>;
  if (error) return <p role="alert">오류: {error}</p>;
  const items = (results || []).slice(0, 10);
  if (!items.length) return <p>결과가 없습니다. 조건을 바꿔보세요.</p>;
  return (
    <div className="results-grid">
      {items.map((r, i) => (
        <ResultCard key={`${r.trademark_id}-${i}`} item={r} index={i} />
      ))}
    </div>
  );
}

function SearchForm({ onSearch }) {
  const [text, setText] = useState("");
  const [cls, setCls] = useState("");
  const [imageFile, setImageFile] = useState(null);
  const TOPN = 10; // 고정 Top-N
  const previewUrl = useMemo(() => (imageFile ? URL.createObjectURL(imageFile) : null), [imageFile]);
  const fileInputRef = useRef(null);

  async function fileToBase64(file) {
    if (!file) return null;
    return new Promise((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result.split(",")[1]);
      reader.readAsDataURL(file);
    });
  }

  const submit = async (e) => {
    e.preventDefault();
    const image = await fileToBase64(imageFile);
    onSearch({ text: text || null, class_code: cls || null, image, topn: TOPN });
  };

  return (
    <form onSubmit={submit} className="search-card">
      <div className="grid inputs">
        <label>
          텍스트
          <input value={text} onChange={(e) => setText(e.target.value)} placeholder="예: tradar" />
        </label>
        <label>
          류 코드
          <input value={cls} onChange={(e) => setCls(e.target.value)} placeholder="예: 30" />
        </label>
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
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInputRef.current?.click(); } }}
        >
          {previewUrl ? (
            <img src={previewUrl} alt="업로드 미리보기" />
          ) : (
            <div className="placeholder">
              <span>이미지를 선택하세요</span>
              <small>클릭하여 파일 선택</small>
            </div>
          )}
        </div>
        <div className="actions-side">
          <button type="submit" className="btn-primary btn-fixed btn-equal">검색</button>
          <button type="reset" className="secondary btn-fixed btn-equal btn-wide" onClick={() => { setText(""); setCls(""); setImageFile(null); }}>초기화</button>
        </div>
      </div>
    </form>
  );
}

function App() {
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const search = async (payload) => {
    setError("");
    setLoading(true);
    try {
      const res = await fetch("/search/trademark", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setResults(data.results || []);
    } catch (e) {
      setError(e?.message || "요청 중 문제가 발생했습니다");
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
          <p className="subtitle">텍스트·이미지 기반 상표 유사도 검색 및 위험도 탐지 서비스</p>
        </div>
      </section>
      <SearchForm onSearch={search} />
      <section>
        <h3>검색 결과</h3>
        <ResultsList results={results} loading={loading} error={error} />
      </section>
    </>
  );
}

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(<App />);
