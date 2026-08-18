import { Link } from '@tanstack/react-router';
import { ExternalLink } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { helpFeatures } from '@/lib/helpData';
import { BOTTOM_SAFE_AREA_PADDING } from '@/lib/constants/ui';
import { cn } from '@/lib/utils/cn';
import { usePlayerStore } from '@/stores/playerStore';

/**
 * Help & tutorial panel.
 *
 * Left: a menu of major features (localized name + English original 병기).
 * Right: the selected feature's title, detailed description, bilingual
 * terminology glossary, and a button that jumps to the feature's tab.
 */
export function HelpTab() {
  const { t } = useTranslation();
  const isPlayerVisible = !!usePlayerStore((s) => s.audioUrl);
  const [selectedId, setSelectedId] = useState<string>(helpFeatures[0].id);
  const selected = helpFeatures.find((f) => f.id === selectedId) ?? helpFeatures[0];
  const SelectedIcon = selected.icon;

  return (
    <div className="h-full flex flex-col min-h-0">
      <header className="shrink-0 pb-4">
        <h1 className="text-2xl font-bold">{t('help.title')}</h1>
        <p className="text-sm text-muted-foreground">{t('help.subtitle')}</p>
      </header>

      <div className="flex flex-1 min-h-0 gap-6">
        {/* Feature menu */}
        <nav className="w-64 shrink-0 overflow-y-auto flex flex-col gap-1 pb-4">
          {helpFeatures.map((feature) => {
            const Icon = feature.icon;
            const isActive = feature.id === selectedId;
            return (
              <button
                key={feature.id}
                type="button"
                onClick={() => setSelectedId(feature.id)}
                aria-current={isActive ? 'true' : undefined}
                className={cn(
                  'flex items-center gap-3 rounded-md px-3 py-2 text-sm text-left transition-colors',
                  isActive
                    ? 'bg-accent/10 text-accent font-medium'
                    : 'text-muted-foreground hover:bg-muted/50 hover:text-foreground',
                )}
              >
                <Icon className="h-4 w-4 shrink-0" />
                <span className="truncate">{t(feature.titleKey)}</span>
              </button>
            );
          })}
        </nav>

        {/* Detail panel */}
        <div
          className={cn(
            'flex-1 min-w-0 overflow-y-auto',
            isPlayerVisible && BOTTOM_SAFE_AREA_PADDING,
          )}
        >
          <div className="max-w-3xl space-y-6">
            <div className="flex items-start gap-3">
              <div className="rounded-lg bg-accent/10 p-2 shrink-0">
                <SelectedIcon className="h-6 w-6 text-accent" />
              </div>
              <div>
                <h2 className="text-xl font-semibold">{t(selected.titleKey)}</h2>
                <p className="text-sm text-muted-foreground mt-2 leading-relaxed">
                  {t(selected.descriptionKey)}
                </p>
              </div>
            </div>

            {/* Bilingual terminology glossary */}
            <section aria-label={t('help.termsLabel')}>
              <h3 className="text-sm font-semibold text-muted-foreground mb-2">
                {t('help.termsLabel')}
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {selected.terms.map((term) => (
                  <div
                    key={term.en}
                    className="flex items-baseline justify-between gap-3 rounded-md border border-border px-3 py-2"
                  >
                    <span className="text-sm font-medium">{term.ko}</span>
                    <span className="text-xs text-muted-foreground font-mono">{term.en}</span>
                  </div>
                ))}
              </div>
            </section>

            {/* Tutorial shortcut */}
            <Link to={selected.path}>
              <Button size="sm">
                {t('help.tutorialAction')}
                <ExternalLink className="h-4 w-4 ml-2" />
              </Button>
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
