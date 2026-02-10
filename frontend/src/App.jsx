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
import { apiFetch, buildApiUrl } from './lib/apiClient';
import { getLandingCopy } from './i18n/landingCopy';

const GOODS_LIMIT = 10;
const RESULT_PAGE_SIZE = 18;
const RESULT_LIMIT = 200;
const SIMULATION_DEFAULT_PER_VARIANT = 5;
const SIMULATION_MAX_SELECTION = 20;
const STATIC_PUBLIC_PREFIX = '/home/work/workspace/tradar/frontend/public';

const buildGoodsSelectionKey = (classCode, groupCode, names = []) => {
  const normalizedNames = Array.isArray(names) ? names.join('|') : '';
  return [classCode || '', groupCode || '', normalizedNames].join('::');
};

const EXAMPLE_PRESETS = {
  example1: {
    title: 'T-RADAR',
    imagePath: '/home/work/workspace/tradar/frontend/public/logo-tradar.png',
    goodsQuery: { ko: '검색', en: 'Retrieval' },
    groups: {
      ko: [
        {
          classCode: '45',
          className: '법률·IP 서비스',
          groupCode: 'S120402',
          names: [
            '상표정보검색조사업',
            '선행기술 조사 및 검색업',
            '온라인 검색가능 데이터베이스를 통한 특허 애플리케이션 분야 정보제공업',
            '칭호검색업',
          ],
        },
        {
          classCode: '35',
          className: '광고·사업관리',
          groupCode: 'S123301',
          names: [
            '인터넷 자료 검색제공업',
            '인터넷상의 정보검색대행업',
            '컴퓨터 데이터베이스 검색업',
            '컴퓨터 자료 검색업',
          ],
        },
        {
          classCode: '38',
          className: '통신 서비스',
          groupCode: 'S0601',
          names: [
            '검색엔진 이용자 접속제공업',
            '스마트폰애플리케이션을 통한 검색엔진 사용자 접속제공업',
            '정보검색용 전자식 온라인 네트워크 접속제공업',
            '정보검색용 전자온라인네트워크 접속제공업',
          ],
        },
        {
          classCode: '09',
          className: '과학·전자기기',
          groupCode: 'G390802',
          names: [
            '검색가능 데이터베이스 생성용 컴퓨터 소프트웨어',
            '데이터 검색용 컴퓨터 소프트웨어',
            '데이터 검색이 가능한 컴퓨터 소프트웨어',
            '정보 및 데이터의 검색 가능한 데이터베이스 제작용 컴퓨터 소프트웨어',
            '컴퓨터 및 컴퓨터네트워크 콘텐츠용 원격검색 컴퓨터프로그램',
            '컴퓨터네트워크를 통한 정보 검색/송신용 소프트웨어',
            '컴퓨터용 검색엔진 소프트웨어',
          ],
        },
      ],
      en: [
        {
          classCode: '45',
          className: 'Legal/IP services',
          groupCode: 'S120402',
          names: ['trademark information retrieval research'],
        },
        {
          classCode: '42',
          className: 'Science & technology services',
          groupCode: 'S123301',
          names: ['design and development of data retrieval software'],
        },
        {
          classCode: '42',
          className: 'Science & technology services',
          groupCode: 'G390802',
          names: ['design and development of data retrieval software'],
        },
        {
          classCode: '35',
          className: 'Advertising & business management',
          groupCode: 'S123301',
          names: [
            'retrieval services for internet data',
            'information retrieval services on the internet for others',
            'computer database retrieval services',
          ],
        },
      ],
    },
  },
  example2: {
    title: 'Hard Rock',
    imagePath: '/home/work/workspace/tradar/frontend/public/logo-hard_rock.jpg',
    goodsQuery: { ko: '맥주', en: 'Beer' },
    groups: {
      ko: [
        {
          classCode: '32',
          className: '무알콜 음료',
          groupCode: 'G0602',
          names: [
            '맥아맥주',
            '맥주',
            '맥주/에일 및 라거',
            '맥주/에일 및 포터',
            '맥주/에일/라거/스타우트 및 포터',
            '맥주용 맥아즙',
            '맥주음료',
            '맥주함유 칵테일',
            '무알코올 맥주',
            '밀맥주',
            '발리 와인(맥주)',
            '비알코올성 맥주',
            '비알코올성 맥주맛 음료',
            '비알코올성 맥주함유 칵테일',
            '비알코올성 맥주향 음료',
            '알코올성분을 제거한 맥주',
            '에일(맥주)',
            '유사맥주',
            '커피맛 맥주',
            '필젠맥주',
          ],
        },
      ],
      en: [
        {
          classCode: '32',
          className: 'Beers',
          groupCode: 'G0602',
          names: [
            'lager beers',
            'low-alcohol beer',
            'root beer',
            'malt beer',
            'beer',
            'beers',
            'beer, ale and lager',
            'beer, ale and porter',
            'beer, ale, lager, stout and porter',
            'beer wort',
            'beer-based beverages',
            'beer-based cocktails',
            'alcohol-free beers',
            'de-alcoholized beer',
            'wheat beer',
            'barley wine [beer]',
            'bock beer',
            'non-alcoholic beer',
            'non-alcoholic beer flavored beverages',
            'non-alcoholic beer-based cocktails',
          ],
        },
      ],
    },
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

const resolveMediaUrl = (input) => {
  if (!input) return '';
  if (input.startsWith('data:')) {
    return input;
  }
  if (input.startsWith('http://') || input.startsWith('https://')) {
    return input;
  }
  let normalized = input;
  if (normalized.startsWith('/api/')) {
    normalized = normalized.slice(4);
  }
  if (!normalized.startsWith('/')) {
    normalized = `/${normalized}`;
  }
  if (normalized.startsWith('/media')) {
    return buildApiUrl(normalized);
  }
  return normalized;
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

const normalizeMarkdown = (value) => {
  if (!value) return '';
  return value
    .replace(/\r\n/g, '\n')
    .replace(/^([\t ]*)[·•▪◦‣⁃⦁●]\s+/gm, '$1- ')
    // 보정: 문장 바로 뒤에 오는 불릿을 명시적 목록으로 인식시키기 위해 빈 줄 삽입
    .replace(/([^\n])\n(-\s+)/g, '$1\n\n$2');
};

const SCORE_THRESHOLDS = [17, 34, 50, 66, 83, 100];
const DEFAULT_SCORE_SEGMENT_LABELS = [
  '매우 낮음',
  '낮음',
  '약간 낮음',
  '약간 높음',
  '높음',
  '매우 높음',
];

const buildScoreSegments = (labels = []) => {
  const safeLabels = Array.isArray(labels) && labels.length === SCORE_THRESHOLDS.length
    ? labels
    : DEFAULT_SCORE_SEGMENT_LABELS;
  return SCORE_THRESHOLDS.map((max, idx) => ({
    label: safeLabels[idx] || DEFAULT_SCORE_SEGMENT_LABELS[idx],
    max,
  }));
};

const clampScore = (value) => Math.max(0, Math.min(100, Number(value) || 0));

const formatScorePill = (value) => {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return value;
  return Math.round(numeric);
};

const describeScoreBand = (value, labels = DEFAULT_SCORE_SEGMENT_LABELS, fallback = '정보 부족') => {
  const clamped = clampScore(value);
  if (!Number.isFinite(clamped)) return fallback;
  if (clamped < 10) return labels[0];
  if (clamped < 30) return labels[1];
  if (clamped < 50) return labels[2];
  if (clamped < 70) return labels[3];
  if (clamped < 90) return labels[4];
  return labels[5];
};

const resolvePointSuffix = (labels = {}) => {
  if (typeof labels.pointSuffix === 'string' && labels.pointSuffix !== '') {
    return labels.pointSuffix;
  }
  const hasEnglish = [labels.avgLabel, labels.maxLabel, labels.minLabel]
    .some((label) => typeof label === 'string' && label.trim() && /[A-Za-z]/.test(label));
  return hasEnglish ? ' pts' : '점';
};

const renderScoreBar = (title, value, secondary, labels = {}) => {
  const segments = buildScoreSegments(labels.segmentLabels);
  const safe = clampScore(value);
  const segmentIndex = segments.findIndex((segment) => safe <= segment.max);
  const hasSecondary = secondary && Number.isFinite(secondary.value);
  const secondaryValue = hasSecondary ? clampScore(secondary.value) : null;
  const mergeThreshold = 20;
  const diff = hasSecondary && secondaryValue !== null
    ? Math.abs(secondaryValue - safe)
    : Infinity;
  const markersOverlap = hasSecondary && secondaryValue !== null && diff < mergeThreshold;
  const avgOffsetClass = markersOverlap
    ? (safe <= (secondaryValue ?? safe) ? 'is-offset-left' : 'is-offset-right')
    : '';
  const secondaryOffsetClass = markersOverlap
    ? (safe <= (secondaryValue ?? safe) ? 'is-offset-right' : 'is-offset-left')
    : '';
  const withinMergeRange = markersOverlap;
  const nearlyEqual = hasSecondary && secondaryValue !== null && diff < 0.25;
  const shouldCombineLabels = nearlyEqual || withinMergeRange;
  const avgComesFirst = secondaryValue !== null && safe <= secondaryValue;
  const avgCollapseClass = shouldCombineLabels
    ? (avgComesFirst ? 'simulation-score-bar__marker-label--collapse-right'
      : 'simulation-score-bar__marker-label--collapse-left')
    : '';
  const markerLabel = secondary?.kind === 'max'
    ? (labels.maxLabel || '최댓값')
    : (labels.minLabel || '최솟값');
  const pointSuffix = resolvePointSuffix(labels);
  const avgLabel = labels.avgLabel || '평균';
  const avgLabelText = `${avgLabel} ${safe.toFixed(1)}${pointSuffix}`;
  const secondaryLabelText = shouldCombineLabels && secondaryValue !== null
    ? null
    : `${markerLabel} ${secondaryValue?.toFixed(1)}${pointSuffix}`;
  return (
    <div className="simulation-score-bar" key={title}>
      <div className="simulation-score-bar__header">
        <span className="simulation-score-bar__title">{title}</span>
      </div>
      <div className="simulation-score-bar__body">
        <div className="simulation-score-bar__track">
          {segments.map((segment, idx) => (
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
            className={`simulation-score-bar__marker simulation-score-bar__marker--${secondary.kind} ${secondaryOffsetClass}`.trim()}
            style={{ left: `${secondaryValue}%` }}
          >
            <span
              className={[
                'simulation-score-bar__marker-label',
                shouldCombineLabels ? 'simulation-score-bar__marker-label--combined' : '',
              ].filter(Boolean).join(' ')}
            >
              {shouldCombineLabels && secondaryValue !== null ? (
                avgComesFirst ? (
                  <>
                    <span className="simulation-score-bar__marker-label-avg">{avgLabelText}</span>
                    <span className="simulation-score-bar__marker-label-divider"> | </span>
                    <span className="simulation-score-bar__marker-label-secondary">
                      {markerLabel} {secondaryValue.toFixed(1)}{pointSuffix}
                    </span>
                  </>
                ) : (
                  <>
                    <span className="simulation-score-bar__marker-label-secondary">
                      {markerLabel} {secondaryValue.toFixed(1)}{pointSuffix}
                    </span>
                    <span className="simulation-score-bar__marker-label-divider"> | </span>
                    <span className="simulation-score-bar__marker-label-avg">{avgLabelText}</span>
                  </>
                )
              ) : (
                secondaryLabelText
              )}
            </span>
            <span className="simulation-score-bar__marker-triangle" />
            <span className="simulation-score-bar__marker-line" />
          </div>
        )}
        <div
          className={`simulation-score-bar__marker simulation-score-bar__marker--avg ${avgOffsetClass}`.trim()}
          style={{ left: `${safe}%` }}
        >
          <span
            className={[
              'simulation-score-bar__marker-label',
              shouldCombineLabels ? 'simulation-score-bar__marker-label--ghost' : '',
              avgCollapseClass,
            ].filter(Boolean).join(' ')}
            aria-hidden={shouldCombineLabels}
          >
            {avgLabelText}
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

function GoodsGroupList({
  classItem,
  expanded,
  onToggleExpand,
  onToggleGroup,
  selectedGroups,
  classBadgeFormat,
}) {
  const hasGroups = classItem.groups && classItem.groups.length > 0;
  if (!hasGroups) return null;
  const classCode = classItem.nc_class;
  const badgeTemplate = classBadgeFormat || '{class}류';
  const badgeLabel = badgeTemplate.replace('{class}', classCode);
  return (
    <article className={`goods-class ${expanded ? 'is-open' : ''}`}>
      <header onClick={() => onToggleExpand(classItem.nc_class)}>
        <div className="goods-class__title">
          <span className="goods-class__badge">{badgeLabel}</span>
          <span className="goods-class__name">{classItem.class_name}</span>
        </div>
        <button type="button" className="icon-button" aria-label="토글">
          {expanded ? '▾' : '▸'}
        </button>
      </header>
      <ul className="goods-class__groups" hidden={!expanded}>
        {classItem.groups.map((group) => {
          const selectionKey = buildGoodsSelectionKey(
            classItem.nc_class,
            group.similar_group_code,
            group.names,
          );
          const checked = Boolean(selectedGroups[selectionKey]);
          return (
            <li key={selectionKey}>
              <label className="goods-group__row">
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={(e) => onToggleGroup({
                    key: selectionKey,
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


function GoodsSearchPanel({ selectedGroups, onToggleGroup, preset, copy, language = 'ko' }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState(new Set());
  const [needsRefresh, setNeedsRefresh] = useState(false);
  const [showLanguageNotice, setShowLanguageNotice] = useState(false);
  const selectedGroupsRef = useRef(selectedGroups);
  const lastSearchedQueryRef = useRef('');
  const lastPresetNonceRef = useRef(null);
  const prevLanguageRef = useRef(language);
  const text = copy || {};

  useEffect(() => {
    selectedGroupsRef.current = selectedGroups;
  }, [selectedGroups]);

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
      const data = await apiFetch(
        `/goods/search?q=${encodeURIComponent(term)}&lang=${encodeURIComponent(language)}`,
      );
      const items = (data?.results || [])
        .filter((item) => Array.isArray(item.groups) && item.groups.length > 0)
        .slice(0, GOODS_LIMIT);
      setResults(items);
      lastSearchedQueryRef.current = term;
      setNeedsRefresh(false);
      setShowLanguageNotice(false);
      if (options.expandSelected) {
        const autoExpanded = new Set();
        const currentGroups = selectedGroupsRef.current || {};
        items.forEach((item) => {
          const hasSelected = item.groups?.some((group) => (
            Boolean(
              currentGroups?.[buildGoodsSelectionKey(
                item.nc_class,
                group.similar_group_code,
                group.names,
              )],
            )
          ));
          if (hasSelected) {
            autoExpanded.add(item.nc_class);
          }
        });
        setExpanded(autoExpanded);
      } else {
        setExpanded(new Set());
      }
    } catch (err) {
      setError(err?.message || text.error || 'An error occurred while searching.');
    } finally {
      setLoading(false);
    }
  }, [language, text.error]);

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
    if (preset.nonce == null || lastPresetNonceRef.current === preset.nonce) {
      return;
    }
    lastPresetNonceRef.current = preset.nonce;
    const term = preset.term || '';
    setQuery(term);
    runGoodsSearch(term, { expandSelected: true });
  }, [preset, runGoodsSearch]);

  useEffect(() => {
    if (prevLanguageRef.current === language) {
      return;
    }
    const hasResults = results.length > 0;
    const hasSelections = Object.keys(selectedGroupsRef.current || {}).length > 0;
    if (hasResults && hasSelections) {
      setNeedsRefresh(true);
      setShowLanguageNotice(true);
    }
    prevLanguageRef.current = language;
  }, [language, results.length]);

  useEffect(() => {
    if (!needsRefresh) {
      return;
    }
    const term = query.trim();
    if (!term || term === lastSearchedQueryRef.current) {
      return;
    }
    const timer = window.setTimeout(() => {
      runGoodsSearch(term, { expandSelected: true });
    }, 500);
    return () => window.clearTimeout(timer);
  }, [needsRefresh, query, runGoodsSearch]);

  const languageNoticeVisible =
    showLanguageNotice && needsRefresh && query.trim() === lastSearchedQueryRef.current;

  return (
    <section className="goods-panel">
      <div className="goods-panel__heading">
        <h2>{text.sectionTitle || '상품/서비스류 검색'}</h2>
        {text.note ? <span className="goods-panel__note">{text.note}</span> : null}
      </div>
      <form className={`goods-search ${needsRefresh ? 'is-attention' : ''}`} onSubmit={fetchGoods}>
        <input
          type="search"
          placeholder={text.placeholder || '예: 커피, 애플리케이션, 교육'}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            if (showLanguageNotice) {
              setShowLanguageNotice(false);
            }
          }}
        />
        {languageNoticeVisible && (
          <div className="goods-search__notice" aria-live="polite">
            <span>
              {text.languageChangeNotice || '언어를 변경하셨습니다. 다시 검색하세요.'}
            </span>
          </div>
        )}
        <button type="submit" className="action-button action-button--primary goods-search__submit">
          <FiSearch aria-hidden="true" />
          <span>{text.search || '검색'}</span>
        </button>
      </form>
      {error && <p role="alert" className="goods-error">{error}</p>}
      {loading && <p>{text.loading || '검색 중입니다…'}</p>}
      {!loading && !error && !results.length && query.trim() && (
        <p>{text.noResults || '일치하는 분류를 찾지 못했습니다.'}</p>
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
            classBadgeFormat={text.classBadgeFormat}
          />
        ))}
      </div>
    </section>
  );
}

function PreviewImage({
  file,
  placeholderTitle = '이미지를 선택하세요',
  placeholderHint = '클릭하여 파일 선택',
  previewAlt = '업로드 미리보기',
}) {
  const url = useMemo(() => (file ? URL.createObjectURL(file) : null), [file]);
  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);
  if (!url) {
    return (
      <div className="placeholder">
        <span className="placeholder__title">{placeholderTitle}</span>
        <small>{placeholderHint}</small>
      </div>
    );
  }
  return <img src={url} alt={previewAlt} />;
}

async function requestPresignedUpload(file, errors = {}) {
  if (!file) {
    throw new Error(errors.noImageFile || 'No image file selected.');
  }
  const payload = {
    filename: file.name || 'upload.bin',
    content_type: file.type || 'application/octet-stream',
  };
  const data = await apiFetch('/media/presign', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!data?.upload_url || !data?.read_url) {
    throw new Error(errors.presignMissing || 'Failed to receive an S3 upload URL.');
  }
  const uploadRes = await fetch(data.upload_url, {
    method: 'PUT',
    headers: { 'Content-Type': data.content_type || payload.content_type },
    body: file,
  });
  if (!uploadRes.ok) {
    throw new Error(errors.uploadFailed || 'Image upload failed.');
  }
  return { type: 'presigned_url', url: data.read_url };
}

function TrademarkSearchForm({
  title,
  onTitleChange,
  imageFile,
  onImageFileChange,
  onSubmit,
  onReset,
  onExample,
  copy,
}) {
  const fileInputRef = useRef(null);
  const [isDragging, setIsDragging] = useState(false);
  const text = copy || {};

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

  const dropzoneClass = [
    'dropzone',
    imageFile ? '' : 'dropzone--empty',
    isDragging ? 'dropzone--drag' : '',
  ].filter(Boolean).join(' ');

  const handleDragOver = (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (event.dataTransfer) {
      event.dataTransfer.dropEffect = 'copy';
    }
    setIsDragging(true);
  };

  const handleDragLeave = (event) => {
    event.preventDefault();
    event.stopPropagation();
    setIsDragging(false);
  };

  const handleDrop = (event) => {
    event.preventDefault();
    event.stopPropagation();
    setIsDragging(false);
    const file = event.dataTransfer?.files?.[0];
    if (!file) {
      return;
    }
    if (file.type && !file.type.startsWith('image/')) {
      return;
    }
    onImageFileChange?.(file);
  };

  return (
    <section className="search-section">
      <div className="search-section__heading">
        <h2>{text.sectionTitle || '상표 검색'}</h2>
        <div
          className="example-button-group"
          role="group"
          aria-label={text.exampleGroupLabel || '예시 불러오기'}
        >
          <button type="button" className="btn-outline" onClick={() => onExample?.('example1')}>
            {text.example1 || '예시 1 : T-RADAR'}
          </button>
          <button type="button" className="btn-outline" onClick={() => onExample?.('example2')}>
            {text.example2 || '예시 2 : Hard Rock'}
          </button>
        </div>
      </div>
      <form className="search-card" onSubmit={handleSubmit} onReset={handleReset}>
        <div className="search-card__top">
          <label className="field-group">
            <span className="field-label">{text.fieldLabel || '상표명'}</span>
            <input
              type="text"
              value={title}
              onChange={(e) => onTitleChange?.(e.target.value)}
              placeholder={text.fieldPlaceholder || '예: 커피한잔'}
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
            onDragOver={handleDragOver}
            onDragEnter={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                fileInputRef.current?.click();
              }
            }}
          >
            <PreviewImage
              file={imageFile}
              placeholderTitle={text.imagePlaceholderTitle}
              placeholderHint={text.imagePlaceholderHint}
              previewAlt={text.imagePreviewAlt}
            />
          </div>
        </div>
      </form>
    </section>
  );
}

function ResultCard({
  item,
  variant,
  simLabel,
  statusLabels,
  emptyImageLabel,
  selectable = false,
  checked = false,
  onToggleSelection,
  canSelectMore = true,
  locked = false,
}) {
  const status = (item.status || '').trim();
  const statusClass = STATUS_MAP[status.toLowerCase()] || 'status-default';
  const displayStatus = translateStatus(status, statusLabels);
  const resolvedSimLabel = simLabel || (variant === 'image' ? '이미지 유사도' : '텍스트 유사도');
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
  const thumbUrl = resolveMediaUrl(item.thumb_url);
  const appNumber = item.application_number || item.applicationNumber || item.app_no || '';
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
          {thumbUrl ? (
            <img src={thumbUrl} alt={`${item.title} 미리보기`} loading="lazy" />
          ) : (
            <div className="thumb-placeholder">{emptyImageLabel || '이미지 없음'}</div>
          )}
        </div>
      </div>
      <div className="result-card__body">
        <header className="result-card__header">
          <strong className="result-title" title={item.title}>{item.title}</strong>
          <span className={`status-badge ${statusClass}`}>{displayStatus}</span>
        </header>
        {appNumber ? (
          <span className="result-card__app-no">{appNumber}</span>
        ) : null}
        <div className="result-divider" />
        <footer className="result-card__footer">
          <span className="result-card__sim-label">{resolvedSimLabel} {simValue?.toFixed ? simValue.toFixed(3) : simValue}</span>
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
  copy,
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
  const text = copy || {};
  const overlayLabel = loadingLabel || text.overlaySearching || '재검색 중…';
  const totalItems = items.length;
  const totalPages = Math.max(1, Math.ceil(totalItems / pageSize));
  const safePage = Math.min(Math.max(page, 1), totalPages);
  const startIdx = (safePage - 1) * pageSize;
  const visibleItems = items.slice(startIdx, startIdx + pageSize);
  const showPagination = totalItems > pageSize && typeof onPageChange === 'function';
  const formatCount = (start, end, total) => {
    if (!total) {
      return text.countZero || '0건';
    }
    const template = text.countFormat || '{start}-{end} / {total}건';
    return template
      .replace('{start}', start)
      .replace('{end}', end)
      .replace('{total}', total);
  };
  const countLabel = formatCount(startIdx + 1, Math.min(totalItems, startIdx + pageSize), totalItems);
  const simLabel = variant === 'image'
    ? (text.simLabelImage || '이미지 유사도')
    : (text.simLabelText || '텍스트 유사도');
  const statusLabels = text.statusLabels || {};
  const emptyImageLabel = text.emptyImage || '이미지 없음';

  return (
    <section className="results-section">
      <div className="results-section__header">
        <div className="results-section__title">
          <h3>{title}</h3>
          <span className="results-section__count">{countLabel}</span>
        </div>
        {highlightMap && Object.keys(highlightMap).length > 0 && (
          <span className="results-section__pill results-section__pill--highlight">
            {text.top5Label || '가장 유사한 상위 5개 상표'}
          </span>
        )}
      </div>
      {hasVariants && (
        <div className="results-section__subheader">
          <span className="results-section__tag">{text.llmTag || 'LLM 유사어'}</span>
          <div className="results-section__variants">
            {variants.map((variant) => (
              <span key={variant} className="results-section__variant">{variant}</span>
            ))}
          </div>
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
                simLabel={simLabel}
                statusLabels={statusLabels}
                emptyImageLabel={emptyImageLabel}
                selectable={selectable}
                checked={Boolean(selectionMap && selectionMap[getResultKey(item)])}
                canSelectMore={Boolean(selectionMap && (selectionMap[getResultKey(item)] || totalSelected < selectionLimit))}
                locked={selectionLocked}
                onToggleSelection={onToggleSelection ? (checked) => onToggleSelection(item, checked) : undefined}
              />
            ))}
          </div>
        ) : (
          <p className="empty">{text.empty || '결과가 없습니다.'}</p>
        )}
        {misc.length ? (
          <div className="results-misc">
            <div className="results-misc__header">
              <h4>{text.miscTitle || '기타 결과'}</h4>
              <span className="results-misc__count">
                {`${misc.length}${text.countSuffix || '건'}`}
              </span>
            </div>
            <div className="results-grid misc-grid">
              {misc.map((item) => (
                <ResultCard
                  key={`${variant}-misc-${item.trademark_id}`}
                  item={item}
                  variant={variant}
                  simLabel={simLabel}
                  statusLabels={statusLabels}
                  emptyImageLabel={emptyImageLabel}
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
  copy,
}) {
  const [focusHighRiskOnly, setFocusHighRiskOnly] = useState(false);
  const text = copy || {};
  const statusText = text.status || {};
  const progressText = text.progress || {};
  const timeText = text.time || {};
  const scoreCopy = text.score || {};
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
    const minuteLabel = timeText.minute || '분';
    const secondLabel = timeText.second || '초';
    return `${minutes}${minuteLabel} ${secs.toString().padStart(2, '0')}${secondLabel}`;
  };
  const shouldShowElapsed =
    ['collecting', 'loading', 'cancelling'].includes(status)
    || (status === 'complete' && elapsedSeconds >= 0);

  const progressSteps = [
    { key: 'collecting', label: progressText.collecting || '데이터 불러오는 중' },
    { key: 'loading', label: progressText.loading || '시뮬레이션 진행' },
    { key: 'complete', label: progressText.complete || '요약 완료' },
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
      title: statusText.idle?.title || '시뮬레이션 준비 필요',
      message: statusText.idle?.message || '검색 후 자동으로 상위 후보가 선택됩니다.',
      tone: 'neutral',
      icon: FiInfo,
    },
    collecting: {
      title: statusText.collecting?.title || '데이터를 불러오는 중',
      message: statusText.collecting?.message || '참고 자료를 수집·정리하는 단계입니다.',
      tone: 'waiting',
      icon: FiFileText,
    },
    loading: {
      title: statusText.loading?.title || '시뮬레이션 진행 중',
      message: statusText.loading?.message || '수집된 자료를 바탕으로 에이전트 시뮬레이션이 진행 중입니다.',
      tone: 'running',
      icon: FiRefreshCcw,
    },
    cancelling: {
      title: statusText.cancelling?.title || '취소 처리 중',
      message: statusText.cancelling?.message || '백엔드 작업을 중단하고 있습니다.',
      tone: 'warning',
      icon: FiStopCircle,
    },
    complete: {
      title: statusText.complete?.title || '결과가 준비되었습니다',
      message: statusText.complete?.message || '아래 요약과 후보별 세부 정보를 확인하세요.',
      tone: 'complete',
      icon: FiCheckCircle,
    },
    error: {
      title: statusText.error?.title || '시뮬레이션에 실패했습니다',
      message: statusText.error?.message || '',
      tone: 'danger',
      icon: FiAlertTriangle,
    },
    cancelled: {
      title: statusText.cancelled?.title || '시뮬레이션이 취소되었습니다',
      message: statusText.cancelled?.message || '필요 시 다시 실행해 주세요.',
      tone: 'warning',
      icon: FiXCircle,
    },
  };
  const currentStatus = statusMetaMap[status] || statusMetaMap.idle;
  const statusMessage = status === 'error'
    ? (error || text.errorFallback || 'Please try again later.')
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
        <span className="simulation-panel__elapsed">
          {text.elapsedLabel || '경과 시간'} {formatElapsed(elapsedSeconds)}
        </span>
      )}
    </div>
  );
  const guidanceLines = Array.isArray(text.guidance) && text.guidance.length
    ? text.guidance.map((line) => line.replace('{maxSelection}', maxSelection))
    : [
        'AI Agent reviews collected materials to estimate conflict risk and registrability.',
        '',
        `- The top 5 image and text candidates are preselected; you can expand up to ${maxSelection}.`,
        '- After clicking “Run Simulation,” you can track steps and elapsed time in real time.',
        '- On completion, each candidate includes a summary, rationale, and dialogue log.',
      ];
  const guidanceMarkdown = guidanceLines.join('\n');
  const guidanceBlock = (
    <MarkdownBlock
      className="simulation-panel__instructions"
      text={guidanceMarkdown}
    />
  );
  const variantLabels = scoreCopy.variantLabels || { image: '이미지', text: '텍스트' };
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
    <aside
      className={panelClass}
      aria-label={text.ariaLabel || '상표 충돌 위험도 및 등록 가능성 시뮬레이션'}
    >
      <div className="simulation-panel__header">
        <p className="simulation-panel__tag">{text.tag || 'AI Agent Simulation'}</p>
        <h3>{text.title || '상표 충돌 위험도 및 등록 가능성 시뮬레이션'}</h3>
      </div>
      <div className="simulation-panel__scrollable">
        <div className="simulation-panel__body">
          <section className="simulation-panel__intro">
            <p className="simulation-panel__description">
              {hasResults
                ? (text.description?.withResults
                  || '기본 설정(이미지 5건 + 텍스트 5건)을 기준으로 최대 20건의 위험도와 등록 가능도를 비교합니다.')
                : (text.description?.noResults
                  || '검색을 먼저 실행하면 위험도가 높은 후보 10건을 자동으로 선택해줍니다.')}
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
                  <p>{text.summary?.image || '이미지 후보'}</p>
                  <strong>{imageCount}</strong>
                </div>
                <div className="simulation-panel__summary-card">
                  <p>{text.summary?.text || '텍스트 후보'}</p>
                  <strong>{textCount}</strong>
                </div>
                <div className="simulation-panel__summary-card">
                  <p>{text.summary?.total || '총 선택 수'}</p>
                  <strong>{totalCount} / {maxSelection}</strong>
                </div>
              </div>
            ) : guidanceBlock}
            {![ 'collecting', 'loading', 'cancelling' ].includes(status) && (
              <div className="simulation-panel__actions">
                <button
                  type="button"
                  className="action-button action-button--primary simulation-panel__button"
                  onClick={() => onRun?.(true)}
                  disabled={buttonDisabled}
                >
                  <FiPlayCircle aria-hidden="true" />
                  <span>{text.buttons?.run || '시뮬레이션 시작'}</span>
                </button>
                {/*
                <button
                  type="button"
                  className="action-button action-button--debug simulation-panel__button"
                  onClick={() => onRun?.(true)}
                  disabled={buttonDisabled}
                >
                  <FiTerminal aria-hidden="true" />
                  <span>시뮬레이션 디버그</span>
                </button>
                */}
              </div>
            )}
            {( ['collecting', 'loading', 'cancelling' ].includes(status) && canCancel) && (
              <button
                type="button"
                className="ghost-button simulation-panel__button"
                onClick={onCancel}
              >
                {text.buttons?.cancel || '실행 취소'}
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
                      scoreCopy.riskTitle || '충돌 위험도',
                      avgConflictScore,
                      Number.isFinite(maxConflictScore)
                        ? { kind: 'max', value: maxConflictScore }
                        : null,
                      scoreCopy,
                    )}
                    {renderScoreBar(
                      scoreCopy.registerTitle || '등록 가능성',
                      avgRegisterScore,
                      Number.isFinite(minRegisterScore)
                        ? { kind: 'min', value: minRegisterScore }
                        : null,
                      scoreCopy,
                    )}
                  </div>
                <div className="simulation-panel__risk-row">
                  <div className="simulation-panel__risk-group">
                    <div className={`simulation-panel__risk-banner ${focusHighRiskOnly && riskToggleEnabled ? 'is-focused' : ''}`}>
                    <div className="simulation-panel__risk-count">
                        <span className="simulation-panel__risk-label">
                          {scoreCopy.highRiskLabel || '높은 위험'}
                        </span>
                        <strong className="simulation-panel__risk-value">
                          {result.high_risk}{scoreCopy.countSuffix || '건'}
                        </strong>
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
                      <span className="risk-average-toggle__label">
                        {scoreCopy.highRiskOnly || '높은 위험만 보기'}
                      </span>
                    </label>
                  </div>
                </div>
              </div>
            )}
              {resultIsStale && (
                <p className="simulation-panel__status-text">
                  {scoreCopy.staleNotice
                    || '새로운 시뮬레이션이 진행 중입니다. 아래 내용은 직전 결과입니다.'}
                </p>
              )}
              <MarkdownBlock
                className="markdown-block--panel"
                text={result.overall_report || result.summary_text}
              />
            </div>
            <div className="simulation-panel__divider" />
            <h4 className="simulation-panel__section-title">
              {scoreCopy.detailTitle || '후보별 상세 분석'}
            </h4>
            <ul className="simulation-panel__list">
              {result.candidates.map((item) => (
                <li key={`sim-${item.application_number}-${item.variant}`}>
                  <details className="simulation-panel__case">
                    <summary>
                      <div className="simulation-panel__case-heading">
                        <div className="simulation-panel__case-info">
                          <div className="simulation-panel__case-thumb">
                            {resolveMediaUrl(item.thumb_url) ? (
                              <img src={resolveMediaUrl(item.thumb_url)} alt={`${item.title} 미리보기`} loading="lazy" />
                            ) : (
                              <span className="simulation-panel__case-thumb-placeholder">
                                {scoreCopy.noImage || '이미지 없음'}
                              </span>
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
                            <label>{scoreCopy.riskLabel || '충돌 위험도'}</label>
                            <strong>
                              {formatScorePill(item.conflict_score)}{resolvePointSuffix(scoreCopy)}
                            </strong>
                          </span>
                          <span className="simulation-panel__score-pill is-safe">
                            <label>{scoreCopy.registerLabel || '등록 가능성'}</label>
                            <strong>
                              {formatScorePill(item.register_score)}{resolvePointSuffix(scoreCopy)}
                            </strong>
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
                          <p className="simulation-panel__section-label">
                            {scoreCopy.rationaleLabel || 'LLM 근거'}
                          </p>
                          <MarkdownBlock
                            className="markdown-block--panel"
                            text={item.llm_rationale}
                          />
                        </div>
                      )}
                      {item.llm_factors?.length ? (
                        <div className="simulation-panel__rationale">
                          <p className="simulation-panel__section-label">
                            {scoreCopy.factorsLabel || '참고 요소'}
                          </p>
                          <ul className="simulation-panel__factor-list">
                            {item.llm_factors.slice(0, 4).map((factor, idx) => (
                              <li key={`factor-${item.application_number}-${idx}`}>{factor}</li>
                            ))}
                          </ul>
                        </div>
                      ) : null}
                      {item.transcript?.length ? (
                        <details className="simulation-panel__transcript">
                          <summary>{scoreCopy.transcriptTitle || '대화 기록 (상위 4턴)'}</summary>
                          <ul>
                            {item.transcript.slice(0, 4).map((line, idx) => {
                              const match = line.match(/^\[(심사관|출원인|리포터|Examiner|Applicant|Reporter)\]\s*\n?([\s\S]*)$/);
                              const speaker = match ? match[1] : '';
                              const content = match ? (match[2] || '').trimStart() : line;
                              const roleKeyMap = {
                                심사관: 'examiner',
                                Examiner: 'examiner',
                                출원인: 'applicant',
                                Applicant: 'applicant',
                                리포터: 'reporter',
                                Reporter: 'reporter',
                              };
                              const roleClassMap = {
                                examiner: 'transcript-entry--examiner',
                                applicant: 'transcript-entry--applicant',
                                reporter: 'transcript-entry--reporter',
                              };
                              const speakerLabels = scoreCopy.speakerLabels || {};
                              const roleKey = roleKeyMap[speaker];
                              const entryClass = roleKey ? roleClassMap[roleKey] : 'transcript-entry--default';
                              const displaySpeaker = roleKey
                                ? (speakerLabels[roleKey] || speaker)
                                : (speaker || speakerLabels.default || '대화');
                              return (
                                <li key={`transcript-${item.application_number}-${idx}`}>
                                  <div className={`transcript-entry ${entryClass}`}>
                                    <div className="transcript-entry__speaker">{displaySpeaker}</div>
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
          <p className="simulation-panel__placeholder">{text.resultLoading || 'Loading results...'}</p>
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
  const [language, setLanguage] = useState('en');
  const [selectedGroups, setSelectedGroups] = useState({});
  const [response, setResponse] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [placeholderNotice, setPlaceholderNotice] = useState('');
  const [imageFile, setImageFile] = useState(null);
  const [title, setTitle] = useState('');
  const [lastImageRef, setLastImageRef] = useState(null);
  const [lastSearchId, setLastSearchId] = useState(null);
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
  const simulationPollRef = useRef(null);
  const copy = useMemo(() => getLandingCopy(language), [language]);
  const searchErrors = copy.search?.errors || {};
  const simulationAlerts = copy.simulation?.alerts || {};
  const simulationErrors = copy.simulation?.errors || {};
  const textDisplayVariants = response?.query?.variants || [];
  const simulationLocked = ['collecting', 'loading', 'cancelling'].includes(simulationStatus);

  useEffect(() => {
    let ignore = false;
    const fetchConfig = async () => {
      try {
        const data = await apiFetch('/simulation/config');
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

  const toggleGroup = ({ key, checked, classCode, className, groupCode, names }) => {
    setSelectedGroups((prev) => {
      const next = { ...prev };
      if (checked) {
        next[key] = { classCode, className, groupCode, names };
      } else {
        delete next[key];
      }
      return next;
    });
  };

  const selectedGroupCodes = useMemo(() => {
    const codes = new Set();
    Object.values(selectedGroups || {}).forEach((item) => {
      if (item?.groupCode) {
        codes.add(item.groupCode);
      }
    });
    return Array.from(codes);
  }, [selectedGroups]);
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
      const data = await apiFetch('/search/multimodal', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
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
      if (payload.image_ref) {
        setLastImageRef(payload.image_ref);
      }
      setLastSearchId(data?.search_id || null);
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
      if (targets.image && targets.text && !simulationResult) {
        resetSimulationProgress();
      }
      setPlaceholderNotice('');
    } catch (err) {
      setError(err?.message || searchErrors.general || 'Search failed.');
    } finally {
      setLoading(false);
      setLoadingState({ image: false, text: false });
    }
  };

  const handleImageFileUpdate = (file) => {
    setImageFile(file);
    setLastImageRef(null);
    setLastSearchId(null);
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
      const groups = Array.isArray(config.groups)
        ? config.groups
        : (config.groups?.[language] || config.groups?.ko || []);
      groups.forEach((group) => {
        if (!group?.groupCode) {
          return;
        }
        const selectionKey = buildGoodsSelectionKey(
          group.classCode,
          group.groupCode,
          group.names,
        );
        groupMap[selectionKey] = {
          classCode: group.classCode,
          className: group.className,
          groupCode: group.groupCode,
          names: group.names || [],
        };
      });
      setTitle(config.title);
      const goodsQuery = typeof config.goodsQuery === 'string'
        ? config.goodsQuery
        : (config.goodsQuery?.[language] || config.goodsQuery?.ko || '');
      setGoodsPreset({ term: goodsQuery, nonce: Date.now() });
      setSelectedGroups(groupMap);
      handleImageFileUpdate(file);
    } catch (err) {
      console.error('Example load failed', err);
      setError(searchErrors.exampleLoad || 'Failed to load the example.');
    }
  };

  const selectedImageCount = Object.keys(simulationSelection.image || {}).length;
  const selectedTextCount = Object.keys(simulationSelection.text || {}).length;
  const totalSimulationSelected = selectedImageCount + selectedTextCount;

  const buildSimulationSelectionRefs = () => {
    const mapRefs = (items = {}, variant) => Object.values(items || {}).map((item) => ({
      application_number: item.app_no,
      variant,
    }));
    const images = mapRefs(simulationSelection.image, 'image');
    const texts = mapRefs(simulationSelection.text, 'text');
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
    if (simulationPollRef.current) {
      window.clearInterval(simulationPollRef.current);
      simulationPollRef.current = null;
    }
  };

  const handleSimulationStatusPayload = (data) => {
    const status = (data?.status || '').toLowerCase();
    if (status === 'pending' || status === 'queued') {
      setSimulationStatus('collecting');
      return false;
    }
    if (status === 'collecting') {
      setSimulationStatus('collecting');
      return false;
    }
    if (status === 'simulating' || status === 'running') {
      setSimulationStatus('loading');
      return false;
    }
    if (status === 'complete' && data?.result) {
      setSimulationStatus('complete');
      setSimulationResult(data.result);
      setSimulationJobId(null);
      setSimulationError('');
      return true;
    }
    if (status === 'failed') {
      setSimulationStatus('error');
      setSimulationError(data?.error || simulationErrors.failed || 'Simulation failed.');
      setSimulationJobId(null);
      return true;
    }
    if (status === 'cancelled') {
      setSimulationStatus('cancelled');
      setSimulationResult((prev) => data.result || prev || null);
      setSimulationJobId(null);
      setSimulationError(simulationErrors.cancelled || 'Simulation was cancelled by the user.');
      return true;
    }
    if (status === 'not_found') {
      setSimulationStatus('error');
      setSimulationError(simulationErrors.notFound || 'Simulation job not found.');
      setSimulationJobId(null);
      return true;
    }
    return false;
  };

  const startSimulationPolling = (jobId) => {
    if (simulationPollRef.current) {
      return;
    }
    const pollOnce = async () => {
      try {
        const data = await apiFetch(`/simulation/status/${jobId}`);
        const done = handleSimulationStatusPayload(data);
        if (done) {
          closeSimulationStream();
        }
      } catch (err) {
        console.error(err);
        setSimulationStatus('error');
        setSimulationError(simulationErrors.statusFetch || 'An error occurred while fetching simulation status.');
        setSimulationJobId(null);
        closeSimulationStream();
      }
    };
    pollOnce();
    simulationPollRef.current = window.setInterval(pollOnce, 2000);
  };

  const startSimulationStream = (jobId) => {
    closeSimulationStream();
    const source = new EventSource(buildApiUrl(`/simulation/stream/${jobId}`));
    simulationEventRef.current = source;
    source.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data || '{}');
        const done = handleSimulationStatusPayload(data);
        if (done) {
          closeSimulationStream();
        }
      } catch (err) {
        console.error(err);
        setSimulationStatus('error');
        setSimulationError(simulationErrors.stream || 'An error occurred while processing the status stream.');
        setSimulationJobId(null);
        closeSimulationStream();
      }
    };
    source.onerror = () => {
      if (simulationEventRef.current) {
        simulationEventRef.current.close();
        simulationEventRef.current = null;
      }
      startSimulationPolling(jobId);
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
            const template = simulationAlerts.selectionLimit || 'You can include up to {max} trademarks.';
            alert(template.replace('{max}', SIMULATION_MAX_SELECTION));
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
      alert(simulationAlerts.searchFirst || 'Please run a search first.');
      return;
    }
    if (!totalSimulationSelected) {
      alert(simulationAlerts.selectTrademarks || 'Please select trademarks to include.');
      return;
    }
    try {
      closeSimulationStream();
      setSimulationStatus('collecting');
      setSimulationError('');
      setSimulationJobId(null);
      setSimulationStartTime(Date.now());
      setSimulationElapsed(0);
      if (!lastSearchId) {
        alert(simulationAlerts.searchContextMissing || 'Search context is missing. Please search again.');
        setSimulationStatus('idle');
        return;
      }
      let imageRef = lastImageRef;
      if (!imageRef && imageFile) {
        imageRef = await requestPresignedUpload(imageFile, searchErrors);
        setLastImageRef(imageRef);
      }
      const selectionRefs = buildSimulationSelectionRefs();
      if (!selectionRefs.length) {
        alert(simulationAlerts.selectTrademarks || 'Please select trademarks to include.');
        setSimulationStatus('idle');
        return;
      }
      const payload = {
        search_id: lastSearchId,
        selection_refs: selectionRefs,
        debug,
        language,
        query_title: (response?.query?.text ?? title ?? '').trim() || null,
        user_goods_classes: response?.query?.goods_classes || [],
        user_group_codes: response?.query?.group_codes || [],
        user_goods_names: buildSelectedGoodsNames(),
        user_image_ref: imageRef || null,
        user_image_mime: imageFile?.type || null,
      };
      const data = await apiFetch('/simulation/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!data?.job_id) {
        throw new Error(simulationErrors.jobIdMissing || 'Failed to receive job ID.');
      }
      setSimulationJobId(data.job_id);
      startSimulationStream(data.job_id);
    } catch (err) {
      console.error(err);
      setSimulationStatus('error');
      setSimulationError(err?.message || simulationErrors.run || 'An error occurred while starting the simulation.');
    }
  };

  const handleSimulationCancel = async () => {
    if (!simulationJobId) {
      return;
    }
    try {
      setSimulationStatus('cancelling');
      await apiFetch(`/simulation/cancel/${simulationJobId}`, {
        method: 'POST',
      });
    } catch (err) {
      console.error(err);
      setSimulationError(simulationErrors.cancel || 'An error occurred while cancelling the simulation.');
    }
  };

  useEffect(() => () => closeSimulationStream(), []);

  const executeSearch = async (debug = false) => {
      if (!imageFile) {
        setPlaceholderNotice('image');
        setError('');
        focusImageUploader();
        return;
      }
    if (selectedGroupCodes.length === 0) {
      setPlaceholderNotice('goods');
      focusGoodsPanel();
      return;
    }
    try {
      const imageRef = await requestPresignedUpload(imageFile, searchErrors);
      await search({
        image_ref: imageRef,
        goods_classes: selectedClassCodes,
        group_codes: selectedGroupCodes,
        k: RESULT_LIMIT,
        text: title.trim() || null,
        debug,
        variants: null,
        use_llm_variants: useLlmVariants,
      }, { image: true, text: true });
    } catch (err) {
      console.error(err);
      alert(searchErrors.requestFailed || 'Search request failed. Check the console.');
    }
  };

  const resetForm = () => {
    setImageFile(null);
    setTitle('');
    setPlaceholderNotice('');
    setLastSearchId(null);
  };

  const toggleLanguage = () => {
    setLanguage((prev) => (prev === 'en' ? 'ko' : 'en'));
  };

  const placeholderCopy = copy.results?.placeholder || {};
  const placeholderKind = placeholderNotice;
  const placeholderTitle = placeholderKind === 'goods'
    ? (placeholderCopy.goodsTitle || '상품/서비스류 선택이 필요합니다')
    : placeholderKind === 'image'
      ? (placeholderCopy.imageTitle || '이미지 업로드가 필요합니다')
      : (placeholderCopy.defaultTitle || '검색을 시작해 주세요');
  const placeholderMessage = placeholderKind === 'goods'
    ? (placeholderCopy.goodsMessage || '상품/서비스류를 선택해 주세요.')
    : placeholderKind === 'image'
      ? (placeholderCopy.imageMessage || '이미지를 먼저 선택하고 검색을 실행해 주세요.')
      : (placeholderCopy.defaultMessage
        || '이미지와 상표명을 입력한 뒤 검색 버튼을 누르면 결과가 여기 표시됩니다.');
  const placeholderActionLabel = placeholderKind === 'goods'
    ? (placeholderCopy.goodsAction || '상품/서비스류 선택하러 가기')
    : (placeholderCopy.imageAction || '이미지 선택하러 가기');

  return (
    <div className="app-shell">
      <div className="search-column">
      <section className="hero">
        <img className="logo" src={logo} alt="T-RADAR" />
        <div className="hero-text">
          <div className="hero-heading">
            <h1 className="title">T-RADAR</h1>
            <div className="hero-actions">
              <button
                type="button"
                className="github-link language-toggle"
                onClick={toggleLanguage}
                aria-label={copy.toggleAria || '언어 전환'}
                title={copy.toggleAria || '언어 전환'}
              >
                <span className="language-toggle__label">
                  <span className="language-toggle__flag" aria-hidden="true">
                    {language === 'en' ? '🇬🇧' : '🇰🇷'}
                  </span>
                  <span className={`language-toggle__item ${language === 'en' ? 'is-active' : ''}`}>Eng</span>
                  <span className="language-toggle__divider">/</span>
                  <span className={`language-toggle__item ${language === 'ko' ? 'is-active' : ''}`}>한</span>
                </span>
              </button>
              <a
                className="github-link hero-github"
                href="https://github.com/yongchoooon/tradar"
                target="_blank"
                rel="noopener noreferrer"
                aria-label={copy.hero?.githubLabel || 'GitHub 저장소'}
                title={copy.hero?.githubLabel || 'GitHub 저장소'}
              >
                <span className="github-link__icon">⭐</span>
                <span className="github-link__label">GitHub</span>
              </a>
            </div>
          </div>
          <p className="subtitle">{copy.hero?.subtitle || '멀티모달 검색과 심사 시뮬레이션으로 상표 충돌 위험을 판단하는 서비스'}</p>
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
        copy={copy.search}
      />
            <GoodsSearchPanel
              selectedGroups={selectedGroups}
              onToggleGroup={toggleGroup}
              preset={goodsPreset}
              copy={copy.goods}
              language={language}
            />
      <div className="search-actions-row">
        <button type="button" className="secondary btn-wide" onClick={resetForm}>
          {copy.search?.reset || '초기화'}
        </button>
        <div className="search-actions">
          <button
            type="button"
            className="action-button action-button--primary"
            onClick={() => executeSearch(false)}
          >
            <FiSearch aria-hidden="true" />
            <span>{copy.search?.search || '검색'}</span>
          </button>
          {/*
          <button
            type="button"
            className="action-button action-button--debug"
            onClick={() => executeSearch(true)}
          >
            <FiTerminal aria-hidden="true" />
            <span>디버그 검색</span>
          </button>
          */}
        </div>
        <label className="llm-toggle" aria-label={copy.search?.llmToggle || 'LLM 유사어 사용 여부'}>
          <input
            id="llm-variants-checkbox"
            type="checkbox"
            checked={useLlmVariants}
            onChange={(e) => setUseLlmVariants(e.target.checked)}
          />
          <span>{copy.search?.llmToggle || 'LLM 유사어'}</span>
        </label>
      </div>
      <section className="search-results">
        <h2>{copy.results?.sectionTitle || '검색 결과'}</h2>
        {error && <p role="alert">{error}</p>}
        <div className="search-results__body">
          <div className="results-main">
            {response ? (
              <>
              <ResultSection
                title={copy.results?.imageTitle || '이미지 후보'}
                items={response.image_top || []}
                misc={response.image_misc || []}
                variant="image"
                loading={loadingState.image}
                loadingLabel={copy.results?.imageUpdating || '이미지 결과 업데이트 중...'}
                copy={copy.results}
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
              <ResultSection
                title={copy.results?.textTitle || '텍스트 후보'}
                items={response.text_top || []}
                misc={response.text_misc || []}
                variant="text"
                variants={textDisplayVariants}
                loading={loadingState.text}
                loadingLabel={copy.results?.textUpdating || '텍스트 결과 업데이트 중...'}
                copy={copy.results}
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
              <DebugPanel debug={response.debug} />
              </>
            ) : (
              <div className="search-placeholder">
              <div className={`search-placeholder__card ${placeholderNotice ? 'is-alert' : ''}`}>
                <h3>
                  {placeholderTitle}
                </h3>
                <p>{placeholderMessage}</p>
                {placeholderNotice && (
                  <button
                    type="button"
                    className="placeholder-action"
                    onClick={
                      placeholderNotice === 'goods'
                        ? focusGoodsPanel
                        : focusImageUploader
                    }
                  >
                    {placeholderActionLabel}
                  </button>
                )}
              </div>
              </div>
            )}
          </div>
          {loading && (
            <div className="search-overlay">
              <span>{copy.results?.loading || '검색 중..'}</span>
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
          copy={copy.simulation}
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
  '포기': 'status-refused',
  'abandoned': 'status-refused',
  'withdrawn': 'status-refused',
  '출원': 'status-pending',
  'pending': 'status-pending',
  '심사중': 'status-pending',
};

const STATUS_LABEL_KEYS = {
  등록: 'registered',
  registered: 'registered',
  공고: 'notice',
  publication: 'notice',
  공지: 'notice',
  거절: 'refused',
  refused: 'refused',
  포기: 'abandoned',
  abandoned: 'abandoned',
  withdrawn: 'abandoned',
  출원: 'pending',
  pending: 'pending',
  심사중: 'pending',
};

const translateStatus = (value, labels = {}) => {
  const raw = (value || '').trim();
  if (!raw) {
    return labels.default || '상태 미상';
  }
  const key = STATUS_LABEL_KEYS[raw] || STATUS_LABEL_KEYS[raw.toLowerCase()];
  if (key && labels[key]) {
    return labels[key];
  }
  return raw;
};

export default App;
