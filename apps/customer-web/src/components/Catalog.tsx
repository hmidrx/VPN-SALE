"use client";
import React from "react";
import { fa, formatDate } from "../i18n/fa";
import {
  createQuote,
  getProduct,
  getProductOptions,
  getQuote,
  listCategories,
  listProducts,
} from "../catalog/api";
import {
  defaultSelection,
  idempotencyKey,
  validateSelection,
} from "../catalog/builder";
import { normalizeComparison } from "../catalog/comparison";
import {
  formatDays,
  formatRial,
  formatTomanFromRial,
  formatTraffic,
  validateComponentSum,
} from "../catalog/format";
import { PreviewController } from "../catalog/preview-controller";
import type {
  Category,
  Option,
  PricePreview,
  ProductDetail,
  ProductOptions,
  ProductSummary,
  Quote,
  QuoteSelection,
} from "../catalog/types";

type CatalogData = {
  categories: Category[];
  products: ProductSummary[];
  loading: boolean;
  error: string | null;
  retry: () => void;
};
function useCatalog(): CatalogData {
  const [attempt, setAttempt] = React.useState(0);
  const [state, setState] = React.useState<Omit<CatalogData, "retry">>({
    categories: [],
    products: [],
    loading: true,
    error: null,
  });
  React.useEffect(() => {
    const ac = new AbortController();
    setState((current) => ({ ...current, loading: true, error: null }));
    void Promise.all([
      listCategories("fa", ac.signal),
      listProducts("fa", ac.signal),
    ])
      .then(([categories, products]) =>
        setState({ categories, products, loading: false, error: null }),
      )
      .catch((error: Error) => {
        if (error.name !== "AbortError")
          setState({
            categories: [],
            products: [],
            loading: false,
            error: error.message,
          });
      });
    return () => ac.abort();
  }, [attempt]);
  return { ...state, retry: () => setAttempt((value) => value + 1) };
}

function CatalogLayout({
  title,
  description,
  count,
  toolbar,
  children,
}: {
  title: string;
  description: string;
  count?: number;
  toolbar?: React.ReactNode;
  children: React.ReactNode;
}): React.ReactElement {
  return (
    <section className="catalog-page">
      <header className="catalog-header">
        <div>
          <span className="catalog-eyebrow">فروشگاه DR.PING</span>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>
        {typeof count === "number" ? (
          <span className="catalog-count">
            {count.toLocaleString("fa-IR")} مورد
          </span>
        ) : null}
      </header>
      {toolbar ? <div className="catalog-toolbar">{toolbar}</div> : null}
      <div className="catalog-content">{children}</div>
    </section>
  );
}
const ArrowIcon = () => (
  <svg aria-hidden="true" viewBox="0 0 24 24">
    <path d="M5 12h14m-6-6 6 6-6 6" />
  </svg>
);
const SearchIcon = () => (
  <svg aria-hidden="true" viewBox="0 0 24 24">
    <circle cx="11" cy="11" r="6" />
    <path d="m16 16 4 4" />
  </svg>
);
const StateIcon = () => (
  <svg aria-hidden="true" viewBox="0 0 24 24">
    <path d="M4 8.5 12 4l8 4.5v7L12 20l-8-4.5zM8 11h8M9.5 14h5" />
  </svg>
);

export function Storefront(): React.ReactElement {
  const data = useCatalog();
  return (
    <CatalogLayout
      title="فروشگاه"
      description="پلن مناسب خود را از میان گزینه‌های فعال انتخاب کنید."
      count={data.products.length}
    >
      <NavTiles />
      {data.loading ? (
        <CatalogSkeleton />
      ) : data.error ? (
        <CatalogState code={data.error} onRetry={data.retry} />
      ) : (
        <>
          <section className="catalog-section">
            <div className="catalog-section-heading">
              <h2>{fa.catalog.categories}</h2>
              <a href="/catalog/categories">مشاهده همه</a>
            </div>
            <CategoryGrid categories={data.categories} />
          </section>
          <section className="catalog-section">
            <div className="catalog-section-heading">
              <h2>پلن‌های پیشنهادی</h2>
              <a href="/catalog/products">مشاهده همه</a>
            </div>
            {data.products.length ? (
              <ProductGrid products={data.products} />
            ) : (
              <CatalogState code="empty" onRetry={data.retry} />
            )}
          </section>
        </>
      )}
    </CatalogLayout>
  );
}
function NavTiles(): React.ReactElement {
  return (
    <nav className="catalog-nav" aria-label="مسیرهای فروشگاه">
      <a href="/catalog/categories">
        {fa.catalog.categories}
        <ArrowIcon />
      </a>
      <a href="/catalog/products">
        {fa.catalog.products}
        <ArrowIcon />
      </a>
      <a href="/catalog/compare">
        {fa.catalog.compare}
        <ArrowIcon />
      </a>
    </nav>
  );
}

function categoryName(category: Category): string {
  return category.name?.trim() || "دسته‌بندی خدمات";
}
function CategoryGrid({
  categories,
}: {
  categories: Category[];
}): React.ReactElement {
  if (!categories.length)
    return <p className="catalog-muted">دسته‌بندی فعالی وجود ندارد.</p>;
  return (
    <div className="catalog-grid catalog-category-grid">
      {categories.map((category) => (
        <article
          className="catalog-card catalog-category-card"
          key={category.id}
        >
          <div className="catalog-card-icon">
            <StateIcon />
          </div>
          <h3>{categoryName(category)}</h3>
          {category.description ? (
            <p>{category.description}</p>
          ) : (
            <p>مشاهده پلن‌های فعال این دسته‌بندی</p>
          )}
          <a
            className="catalog-link"
            href={`/catalog/products?category=${category.id}`}
          >
            مشاهده محصولات <ArrowIcon />
          </a>
        </article>
      ))}
    </div>
  );
}
export function CategoriesPage(): React.ReactElement {
  const data = useCatalog();
  return (
    <CatalogLayout
      title="دسته‌بندی‌ها"
      description="سرویس‌ها را بر اساس نیاز خود مرور کنید."
      count={data.loading ? undefined : data.categories.length}
    >
      {data.loading ? (
        <CatalogSkeleton count={3} />
      ) : data.error ? (
        <CatalogState code={data.error} onRetry={data.retry} />
      ) : data.categories.length ? (
        <CategoryGrid categories={data.categories} />
      ) : (
        <CatalogState code="empty-categories" onRetry={data.retry} />
      )}
    </CatalogLayout>
  );
}

export function ProductsPage(): React.ReactElement {
  const data = useCatalog();
  const [query, setQuery] = React.useState("");
  const [category, setCategory] = React.useState("");
  React.useEffect(() => {
    setCategory(
      new URLSearchParams(window.location.search).get("category") ?? "",
    );
  }, []);
  const normalized = query.trim().toLocaleLowerCase("fa");
  const categoryProducts = category
    ? data.products.filter((product) => product.category_id === category)
    : data.products;
  const filtered = categoryProducts.filter((product) =>
    `${product.name ?? ""} ${product.description ?? ""} ${product.machine_code}`
      .toLocaleLowerCase("fa")
      .includes(normalized),
  );
  const toolbar = (
    <>
      <label className="catalog-search">
        <span className="sr-only">جست‌وجوی محصولات</span>
        <SearchIcon />
        <input
          value={query}
          maxLength={80}
          dir="auto"
          placeholder="جست‌وجوی پلن یا سرویس"
          onKeyDown={(event) => {
            if (event.key === "Escape") setQuery("");
          }}
          onChange={(event) => setQuery(event.currentTarget.value)}
        />
        {query ? (
          <button
            type="button"
            aria-label="پاک‌کردن جست‌وجو"
            onClick={() => setQuery("")}
          >
            پاک‌کردن
          </button>
        ) : null}
      </label>
      {data.categories.length ? (
        <div className="catalog-filters" aria-label="فیلتر دسته‌بندی">
          <button aria-pressed={!category} onClick={() => setCategory("")}>
            همه
          </button>
          {data.categories.map((item) => (
            <button
              key={item.id}
              aria-pressed={category === item.id}
              onClick={() => setCategory(item.id)}
            >
              {categoryName(item)}
            </button>
          ))}
        </div>
      ) : null}
    </>
  );
  return (
    <CatalogLayout
      title="محصولات"
      description="پلن‌ها را جست‌وجو و با نیازتان مقایسه کنید."
      count={data.loading ? undefined : filtered.length}
      toolbar={toolbar}
    >
      {data.loading ? (
        <CatalogSkeleton />
      ) : data.error ? (
        <CatalogState code={data.error} onRetry={data.retry} />
      ) : !data.products.length ? (
        <CatalogState code="empty" onRetry={data.retry} />
      ) : !filtered.length ? (
        <CatalogState
          code="no-results"
          query={query}
          onClear={() => {
            setQuery("");
            setCategory("");
          }}
        />
      ) : (
        <ProductGrid products={filtered} categories={data.categories} />
      )}
    </CatalogLayout>
  );
}
function ProductGrid({
  products,
  categories = [],
}: {
  products: ProductSummary[];
  categories?: Category[];
}): React.ReactElement {
  const names = new Map(
    categories.map((category) => [category.id, categoryName(category)]),
  );
  return (
    <div className="catalog-grid">
      {products.map((product) => (
        <article className="catalog-card catalog-product-card" key={product.id}>
          {names.get(product.category_id) ? (
            <span className="catalog-badge">
              {names.get(product.category_id)}
            </span>
          ) : null}
          <h2>{product.name?.trim() || "پلن خدمات شبکه"}</h2>
          {product.description ? (
            <p>{product.description}</p>
          ) : (
            <p>جزئیات و گزینه‌های قابل انتخاب این پلن را مشاهده کنید.</p>
          )}
          <div className="catalog-card-actions">
            <a
              className="catalog-primary"
              href={`/catalog/products/${product.id}`}
            >
              مشاهده و انتخاب <ArrowIcon />
            </a>
            <a
              className="catalog-secondary"
              href={`/catalog/compare?ids=${product.id}`}
            >
              {fa.catalog.addCompare}
            </a>
          </div>
        </article>
      ))}
    </div>
  );
}

function useProduct(id: string): {
  product?: ProductDetail;
  options?: ProductOptions;
  error?: string;
} {
  const [state, setState] = React.useState<{
    product?: ProductDetail;
    options?: ProductOptions;
    error?: string;
  }>({});
  React.useEffect(() => {
    const ac = new AbortController();
    void Promise.all([
      getProduct(id, "fa", ac.signal),
      getProductOptions(id, ac.signal),
    ])
      .then(([product, options]) => setState({ product, options }))
      .catch((error: Error) => {
        if (error.name !== "AbortError") setState({ error: error.message });
      });
    return () => ac.abort();
  }, [id]);
  return state;
}
export function ProductPage({
  productId,
}: {
  productId: string;
}): React.ReactElement {
  const { product, options, error } = useProduct(productId);
  if (error)
    return (
      <CatalogLayout title="جزئیات پلن" description="اطلاعات سرویس انتخابی">
        <CatalogState code={error} />
      </CatalogLayout>
    );
  if (!product || !options)
    return (
      <CatalogLayout title="جزئیات پلن" description="اطلاعات سرویس انتخابی">
        <CatalogSkeleton count={1} />
      </CatalogLayout>
    );
  const route = options.product_type === "FIXED_PLAN" ? "fixed" : "custom";
  const values = options.options;
  return (
    <CatalogLayout
      title={product.name?.trim() || "جزئیات پلن"}
      description={
        product.description || "ویژگی‌های این پلن را بررسی و سپس انتخاب کنید."
      }
    >
      <a className="catalog-back" href="/catalog/products">
        <ArrowIcon /> بازگشت به محصولات
      </a>
      <article className="catalog-detail">
        <span className="catalog-badge">
          {route === "fixed" ? "پلن آماده" : "پلن اختصاصی"}
        </span>
        <h2>ویژگی‌های سرویس</h2>
        <dl className="catalog-attributes">
          <Field
            label={fa.catalog.traffic}
            value={
              values.fixed_traffic_bytes
                ? formatTraffic(values.fixed_traffic_bytes)
                : `${formatTraffic(values.traffic.minimum)} تا ${formatTraffic(values.traffic.maximum)}`
            }
          />
          <Field
            label={fa.catalog.duration}
            value={
              values.fixed_duration_days
                ? formatDays(values.fixed_duration_days)
                : `${formatDays(values.duration_days.minimum)} تا ${formatDays(values.duration_days.maximum)}`
            }
          />
          {values.fixed_device_count ? (
            <Field
              label={fa.catalog.devices}
              value={values.fixed_device_count.toLocaleString("fa-IR")}
            />
          ) : null}
          {values.location_options.length ? (
            <Field
              label={fa.catalog.location}
              value={values.location_options.map(optionLabel).join("، ")}
            />
          ) : null}
          {values.quality_options.length ? (
            <Field
              label={fa.catalog.quality}
              value={values.quality_options.map(optionLabel).join("، ")}
            />
          ) : null}
        </dl>
        <div className="catalog-card-actions">
          <a
            className="catalog-primary"
            href={`/catalog/products/${product.id}/${route}`}
          >
            {route === "fixed" ? fa.catalog.fixed : fa.catalog.custom}
          </a>
          <a
            className="catalog-secondary"
            href={`/catalog/compare?ids=${product.id}`}
          >
            {fa.catalog.compare}
          </a>
        </div>
      </article>
    </CatalogLayout>
  );
}

function optionLabel(option: Option): string {
  if (Array.isArray(option.labels))
    return (
      option.labels.find((item) => item.locale === "fa")?.value ||
      option.labels[0]?.value ||
      option.description ||
      option.code
    );
  return (
    option.labels?.fa || option.labels?.en || option.description || option.code
  );
}
export function BuilderPage({
  productId,
}: {
  productId: string;
}): React.ReactElement {
  const { product, options, error } = useProduct(productId);
  const [selection, setSelection] = React.useState<QuoteSelection | null>(null);
  const [preview, setPreview] = React.useState<PricePreview | null>(null);
  const [message, setMessage] = React.useState<string | null>(null);
  const [previewing, setPreviewing] = React.useState(false);
  const [quoting, setQuoting] = React.useState(false);
  const controller = React.useMemo(() => new PreviewController(), []);
  React.useEffect(() => {
    if (options && !selection)
      setSelection(defaultSelection(productId, options));
  }, [options, productId, selection]);
  React.useEffect(() => () => controller.cancel(), [controller]);
  if (error)
    return (
      <CatalogLayout title="ساخت پلن" description="تنظیم گزینه‌های سرویس">
        <CatalogState code={error} />
      </CatalogLayout>
    );
  if (!product || !options || !selection)
    return (
      <CatalogLayout title="ساخت پلن" description="تنظیم گزینه‌های سرویس">
        <CatalogSkeleton count={2} />
      </CatalogLayout>
    );
  const errors = validateSelection(selection, options);
  const update = (patch: Partial<QuoteSelection>) => {
    setPreview(null);
    setMessage(null);
    setSelection({ ...selection, ...patch });
  };
  const doPreview = async () => {
    if (previewing || errors.length) {
      setMessage(errors[0]?.message ?? null);
      return;
    }
    setPreviewing(true);
    setMessage(null);
    try {
      setPreview(await controller.request(selection));
      setMessage(fa.catalog.nonBinding);
    } catch {
      setMessage("محاسبه قیمت انجام نشد. لطفاً دوباره تلاش کنید.");
    } finally {
      setPreviewing(false);
    }
  };
  const doQuote = async () => {
    if (!preview || quoting) return;
    setQuoting(true);
    try {
      const quote = await createQuote(selection, idempotencyKey());
      location.href = `/catalog/quotes/${quote.quote_reference}`;
    } catch {
      setMessage("ایجاد پیش‌فاکتور انجام نشد. دوباره تلاش کنید.");
      setQuoting(false);
    }
  };
  return (
    <CatalogLayout
      title={
        options.product_type === "FIXED_PLAN"
          ? fa.catalog.fixed
          : fa.catalog.custom
      }
      description={product.name?.trim() || "تنظیم پلن انتخابی"}
    >
      <a className="catalog-back" href={`/catalog/products/${productId}`}>
        <ArrowIcon /> بازگشت به جزئیات
      </a>
      <div className="builder-layout">
        <section className="builder-surface">
          <div className="builder-step">
            <span>۱</span>
            <div>
              <h2>مشخصات مصرف</h2>
              <p>حجم، مدت و تعداد دستگاه را مشخص کنید.</p>
            </div>
          </div>
          <div className="builder-fields">
            <NumberInput
              label={fa.catalog.traffic}
              value={selection.traffic_bytes}
              disabled={Boolean(options.options.fixed_traffic_bytes)}
              onChange={(traffic_bytes) => update({ traffic_bytes })}
            />
            <NumberInput
              label={fa.catalog.duration}
              value={selection.duration_days}
              disabled={Boolean(options.options.fixed_duration_days)}
              onChange={(duration_days) => update({ duration_days })}
            />
            <NumberInput
              label={fa.catalog.devices}
              value={selection.device_count}
              disabled={Boolean(options.options.fixed_device_count)}
              onChange={(device_count) => update({ device_count })}
            />
          </div>
          <div className="builder-step">
            <span>۲</span>
            <div>
              <h2>موقعیت و کیفیت</h2>
              <p>گزینه مناسب اتصال را انتخاب کنید.</p>
            </div>
          </div>
          <div className="builder-fields">
            <Select
              label={fa.catalog.location}
              value={selection.location_code}
              options={options.options.location_options}
              onChange={(location_code) => update({ location_code })}
            />
            <Select
              label={fa.catalog.quality}
              value={selection.quality_code}
              options={options.options.quality_options}
              onChange={(quality_code) => update({ quality_code })}
            />
          </div>
          {errors.length ? (
            <div className="builder-error" role="alert">
              {errors[0]?.message}
            </div>
          ) : null}
          <button
            className="catalog-primary builder-preview"
            disabled={previewing || Boolean(errors.length)}
            onClick={() => void doPreview()}
          >
            {previewing ? "در حال محاسبه…" : fa.catalog.preview}
          </button>
          <div aria-live="polite" className="catalog-message">
            {message}
          </div>
        </section>
        <aside className="builder-summary">
          {preview ? (
            <PriceBreakdown preview={preview} />
          ) : (
            <div className="builder-placeholder">
              <StateIcon />
              <h2>خلاصه قیمت</h2>
              <p>پس از تکمیل گزینه‌ها، قیمت معتبر سرور را محاسبه کنید.</p>
            </div>
          )}
          <button
            className="catalog-primary"
            disabled={!preview || quoting}
            onClick={() => void doQuote()}
          >
            {quoting ? "در حال ایجاد…" : fa.catalog.quote}
          </button>
        </aside>
      </div>
    </CatalogLayout>
  );
}
function NumberInput({
  label,
  value,
  disabled,
  onChange,
}: {
  label: string;
  value: number;
  disabled?: boolean;
  onChange: (value: number) => void;
}): React.ReactElement {
  return (
    <label className="catalog-field">
      <span>{label}</span>
      <input
        dir="ltr"
        type="number"
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(Number(event.currentTarget.value))}
      />
    </label>
  );
}
function Select({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: Option[];
  onChange: (value: string) => void;
}): React.ReactElement {
  return (
    <label className="catalog-field">
      <span>{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.currentTarget.value)}
      >
        {options.map((option) => (
          <option
            disabled={option.enabled === false}
            value={option.code}
            key={option.code}
          >
            {optionLabel(option)}
          </option>
        ))}
      </select>
    </label>
  );
}

const componentLabels: Record<string, string> = {
  base: "هزینه پایه",
  traffic: "ترافیک",
  duration: "مدت",
  devices: "تعداد دستگاه",
  location: "موقعیت",
  quality: "کیفیت",
  discount: "تخفیف",
  tax: "مالیات",
};
function PriceBreakdown({
  preview,
}: {
  preview: PricePreview | Quote;
}): React.ReactElement {
  if (!validateComponentSum(preview.subtotal_minor, preview.components))
    return (
      <div className="catalog-inline-state compact" role="alert">
        <h2>نمایش قیمت ممکن نیست</h2>
        <p>پاسخ قیمت معتبر نبود. لطفاً دوباره محاسبه کنید.</p>
      </div>
    );
  return (
    <section className="price-card">
      <header>
        <div>
          <span>خلاصه قیمت</span>
          <h2>مبلغ پلن</h2>
        </div>
        <small>{preview.currency === "IRR" ? "ریال" : "واحد ثبت‌شده"}</small>
      </header>
      <div className="price-row">
        <span>جمع اجزا</span>
        <b>{formatRial(preview.subtotal_minor)}</b>
      </div>
      {preview.components.map((component) => (
        <div
          className="price-row component"
          key={`${component.order}-${component.code}`}
        >
          <span>
            {component.label || componentLabels[component.code] || "جزء قیمت"}
          </span>
          <b>{formatRial(component.amount_minor)}</b>
        </div>
      ))}
      <div className="price-final">
        <span>مبلغ نهایی</span>
        <div>
          <strong>{formatRial(preview.final_amount_minor)}</strong>
          <small>{formatTomanFromRial(preview.final_amount_minor)}</small>
        </div>
      </div>
      <p>
        {"binding" in preview
          ? fa.catalog.nonBinding
          : "مبلغ این پیش‌فاکتور توسط سرور ثبت شده است."}
      </p>
    </section>
  );
}
export function QuotePage({
  reference,
}: {
  reference: string;
}): React.ReactElement {
  const [quote, setQuote] = React.useState<Quote | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    const ac = new AbortController();
    void getQuote(reference, ac.signal)
      .then(setQuote)
      .catch((failure: Error) => {
        if (failure.name !== "AbortError") setError(failure.message);
      });
    return () => ac.abort();
  }, [reference]);
  if (error)
    return (
      <CatalogLayout title="پیش‌فاکتور" description="مرور انتخاب و قیمت">
        <CatalogState code={error} />
      </CatalogLayout>
    );
  if (!quote)
    return (
      <CatalogLayout title="پیش‌فاکتور" description="مرور انتخاب و قیمت">
        <CatalogSkeleton count={2} />
      </CatalogLayout>
    );
  const expired =
    quote.status !== "ACTIVE" ||
    new Date(quote.expires_at).getTime() <= Date.now();
  return (
    <CatalogLayout
      title="مرور پیش‌فاکتور"
      description="پیش از ادامه، مشخصات و مبلغ را بررسی کنید."
    >
      <div className={`quote-status ${expired ? "expired" : "active"}`}>
        <strong>{expired ? "پیش‌فاکتور منقضی شده" : "پیش‌فاکتور فعال"}</strong>
        <span>اعتبار تا {formatDate(quote.expires_at)}</span>
      </div>
      <div className="quote-layout">
        <section className="catalog-detail">
          <h2>خلاصه انتخاب</h2>
          <dl className="catalog-attributes">
            {Object.entries(quote.selected_options).map(([key, value]) => (
              <Field
                key={key}
                label={componentLabels[key] || "گزینه انتخابی"}
                value={String(value)}
              />
            ))}
            <Field label="زمان صدور" value={formatDate(quote.issued_at)} />
          </dl>
          <details>
            <summary>جزئیات فنی پیش‌فاکتور</summary>
            <code>{quote.quote_reference}</code>
          </details>
        </section>
        <PriceBreakdown preview={quote} />
      </div>
      <div className="catalog-card-actions">
        {!expired ? (
          <a
            className="catalog-primary"
            href={`/checkout/${quote.quote_reference}`}
          >
            ادامه و پرداخت از کیف پول
          </a>
        ) : (
          <a
            className="catalog-primary"
            href={`/catalog/products/${quote.product_id}`}
          >
            {fa.catalog.recalc}
          </a>
        )}
        <a className="catalog-secondary" href="/catalog/products">
          بازگشت به محصولات
        </a>
      </div>
    </CatalogLayout>
  );
}
function ComparisonItem({
  id,
  allIds,
}: {
  id: string;
  allIds: string[];
}): React.ReactElement {
  const { product, options, error } = useProduct(id);
  const remaining = allIds.filter((item) => item !== id).join(",");
  if (error) return <CatalogState code={error} />;
  if (!product || !options) return <div className="catalog-skeleton-card" />;
  return (
    <article className="comparison-card">
      <h2>{product.name?.trim() || "پلن خدمات شبکه"}</h2>
      <p>
        {product.description ||
          "اطلاعات این پلن را با گزینه‌های دیگر مقایسه کنید."}
      </p>
      <dl>
        <Field
          label="نوع پلن"
          value={options.product_type === "FIXED_PLAN" ? "آماده" : "اختصاصی"}
        />
        <Field
          label={fa.catalog.traffic}
          value={
            options.options.fixed_traffic_bytes
              ? formatTraffic(options.options.fixed_traffic_bytes)
              : "قابل انتخاب"
          }
        />
        <Field
          label={fa.catalog.duration}
          value={
            options.options.fixed_duration_days
              ? formatDays(options.options.fixed_duration_days)
              : "قابل انتخاب"
          }
        />
      </dl>
      <div className="catalog-card-actions">
        <a className="catalog-primary" href={`/catalog/products/${id}`}>
          انتخاب پلن
        </a>
        <a
          className="catalog-secondary"
          href={
            remaining ? `/catalog/compare?ids=${remaining}` : "/catalog/compare"
          }
        >
          حذف
        </a>
      </div>
    </article>
  );
}
export function ComparePage({
  ids = "",
}: {
  ids?: string;
}): React.ReactElement {
  const list = normalizeComparison(ids.split(","));
  return (
    <CatalogLayout
      title={fa.catalog.compare}
      description="تا سه پلن را کنار هم بررسی کنید."
      count={list.length}
    >
      {list.length ? (
        <>
          <div className="comparison-grid">
            {list.map((id) => (
              <ComparisonItem id={id} allIds={list} key={id} />
            ))}
          </div>
          <a className="catalog-back" href="/catalog/products">
            <ArrowIcon /> افزودن یا تغییر پلن‌ها
          </a>
        </>
      ) : (
        <CatalogState code="compare-empty" />
      )}
    </CatalogLayout>
  );
}

function Field({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}): React.ReactElement {
  return (
    <div className="catalog-attribute">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
function CatalogSkeleton({
  count = 4,
}: {
  count?: number;
}): React.ReactElement {
  return (
    <div
      className="catalog-grid"
      aria-label="در حال بارگذاری"
      aria-live="polite"
    >
      {Array.from({ length: count }, (_, index) => (
        <div className="catalog-skeleton-card" key={index}>
          <i />
          <i />
          <i />
        </div>
      ))}
    </div>
  );
}
export function CatalogState({
  code,
  query,
  onRetry,
  onClear,
}: {
  code: string;
  query?: string;
  onRetry?: () => void;
  onClear?: () => void;
}): React.ReactElement {
  const noResults = code === "no-results";
  const empty = code === "empty" || code === "empty-categories";
  const compareEmpty = code === "compare-empty";
  const title = noResults
    ? "نتیجه‌ای پیدا نشد"
    : empty
      ? code === "empty"
        ? "هنوز پلنی برای نمایش وجود ندارد"
        : "هنوز دسته‌بندی فعالی وجود ندارد"
      : compareEmpty
        ? "هنوز پلنی برای مقایسه انتخاب نشده"
        : code === "rate_limited"
          ? "کمی بعد دوباره تلاش کنید"
          : code === "service_unavailable"
            ? "فروشگاه موقتاً در دسترس نیست"
            : code === "not_found"
              ? "مورد درخواستی پیدا نشد"
              : "ارتباط با فروشگاه برقرار نشد";
  const description = noResults ? (
    <>
      برای «<b dir="auto">{query}</b>» موردی پیدا نشد. عبارت دیگری را امتحان
      کنید.
    </>
  ) : empty ? (
    "به‌محض فعال‌شدن پلن‌ها، از همین بخش می‌توانید آن‌ها را ببینید و انتخاب کنید."
  ) : compareEmpty ? (
    "از صفحه محصولات، پلن‌های موردنظر را برای مقایسه انتخاب کنید."
  ) : (
    "اطلاعات فنی نمایش داده نمی‌شود؛ اتصال خود را بررسی و دوباره تلاش کنید."
  );
  return (
    <div
      className="catalog-inline-state"
      role={empty || compareEmpty ? "status" : "alert"}
      aria-live="polite"
    >
      <div className="catalog-state-icon">
        <StateIcon />
      </div>
      <h2>{title}</h2>
      <p>{description}</p>
      {noResults && onClear ? (
        <button className="catalog-secondary" onClick={onClear}>
          پاک‌کردن جست‌وجو
        </button>
      ) : onRetry ? (
        <button className="catalog-primary" onClick={onRetry}>
          تلاش دوباره
        </button>
      ) : compareEmpty ? (
        <a className="catalog-primary" href="/catalog/products">
          مشاهده محصولات
        </a>
      ) : null}
    </div>
  );
}
