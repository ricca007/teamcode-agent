import { setLocale, useLocale } from "../i18n";

/** 中/英切换按钮，供顶栏与登录页共用。 */
export function LanguageToggle() {
  const locale = useLocale();
  return (
    <div
      className="segmented segmented--sm"
      role="group"
      aria-label="Language / 语言"
    >
      <button
        type="button"
        aria-pressed={locale === "zh"}
        onClick={() => setLocale("zh")}
      >
        中
      </button>
      <button
        type="button"
        aria-pressed={locale === "en"}
        onClick={() => setLocale("en")}
      >
        EN
      </button>
    </div>
  );
}
