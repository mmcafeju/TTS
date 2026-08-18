import { Link } from '@tanstack/react-router';
import { ExternalLink } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import {
  getHelpFeature,
  getHelpTutorial,
  helpFeatures,
  helpMenuOrder,
  helpOverview,
  helpTutorials,
  type HelpMenuItemId,
  type HelpTutorial,
} from '@/lib/helpData';
import { BOTTOM_SAFE_AREA_PADDING } from '@/lib/constants/ui';
import { cn } from '@/lib/utils/cn';
import { usePlayerStore } from '@/stores/playerStore';

interface HelpSpec {
  label: string;
  value: string;
}

/**
 * Help & tutorial panel.
 *
 * Left menu: app overview, every major feature (localized name + English
 * original 병기), and the step-by-step tutorials. The right panel renders the
 * selected item — overview specs, feature details, or a numbered tutorial with
 * high-quality specs and a jump button to the related tab.
 */
export function HelpTab() {
  const { t } = useTranslation();
  const isPlayerVisible = !!usePlayerStore((s) => s.audioUrl);
  const [selectedId, setSelectedId] = useState<HelpMenuItemId>('overview');

  const renderPanel = () => {
    if (selectedId === helpOverview.id) {
      return (
        <OverviewPanel
          title={t(helpOverview.titleKey)}
          description={t(helpOverview.descriptionKey)}
          Icon={helpOverview.icon}
          specsKey={helpOverview.specsKey}
          featuresKey={helpOverview.featuresKey}
        />
      );
    }

    const tutorial = getHelpTutorial(selectedId);
    if (tutorial) {
      return <TutorialPanel tutorial={tutorial} />;
    }

    const feature = getHelpFeature(selectedId);
    return <FeaturePanel featureId={feature.id} />;
  };

  return (
    <div className="h-full flex flex-col min-h-0">
      <header className="shrink-0 pb-4">
        <h1 className="text-2xl font-bold">{t('help.title')}</h1>
        <p className="text-sm text-muted-foreground">{t('help.subtitle')}</p>
      </header>

      <div className="flex flex-1 min-h-0 gap-6">
        {/* Left menu */}
        <nav className="w-64 shrink-0 overflow-y-auto flex flex-col gap-1 pb-4">
          {helpMenuOrder.map((id) => {
            const feature = helpFeatures.find((f) => f.id === id);
            const tutorial = helpTutorials.find((tt) => tt.id === id);
            const isOverview = id === helpOverview.id;
            const Icon = isOverview
              ? helpOverview.icon
              : feature?.icon ?? tutorial?.icon;
            const label = isOverview
              ? t(helpOverview.titleKey)
              : feature
                ? t(feature.titleKey)
                : t(tutorial!.titleKey);
            const isActive = id === selectedId;

            return (
              <button
                key={id}
                type="button"
                onClick={() => setSelectedId(id)}
                aria-current={isActive ? 'true' : undefined}
                className={cn(
                  'flex items-center gap-3 rounded-md px-3 py-2 text-sm text-left transition-colors',
                  isActive
                    ? 'bg-accent/10 text-accent font-medium'
                    : 'text-muted-foreground hover:bg-muted/50 hover:text-foreground',
                )}
              >
                {Icon ? <Icon className="h-4 w-4 shrink-0" /> : null}
                <span className="truncate">{label}</span>
                {tutorial ? (
                  <span className="ml-auto shrink-0 text-[10px] text-muted-foreground/70">
                    {tutorial.index}
                  </span>
                ) : null}
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
          <div className="max-w-3xl space-y-6">{renderPanel()}</div>
        </div>
      </div>
    </div>
  );
}

function SpecTable({ specsKey }: { specsKey: string }) {
  const { t } = useTranslation();
  const specs = t(specsKey, { returnObjects: true }) as HelpSpec[];
  return (
    <div className="grid grid-cols-1 gap-2">
      {specs.map((spec) => (
        <div
          key={spec.label}
          className="flex items-baseline justify-between gap-3 rounded-md border border-border px-3 py-2"
        >
          <span className="text-sm font-medium shrink-0">{spec.label}</span>
          <span className="text-xs text-muted-foreground text-right">
            {spec.value}
          </span>
        </div>
      ))}
    </div>
  );
}

function TermsGrid({ terms }: { terms: { ko: string; en: string }[] }) {
  const { t } = useTranslation();
  return (
    <section aria-label={t('help.termsLabel')}>
      <h3 className="text-sm font-semibold text-muted-foreground mb-2">
        {t('help.termsLabel')}
      </h3>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {terms.map((term) => (
          <div
            key={term.en}
            className="flex items-baseline justify-between gap-3 rounded-md border border-border px-3 py-2"
          >
            <span className="text-sm font-medium">{term.ko}</span>
            <span className="text-xs text-muted-foreground font-mono">
              {term.en}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

interface PanelHeaderProps {
  title: string;
  subtitle?: string;
  Icon: React.ComponentType<{ className?: string }>;
}

function PanelHeader({ title, subtitle, Icon }: PanelHeaderProps) {
  return (
    <div className="flex items-start gap-3">
      <div className="rounded-lg bg-accent/10 p-2 shrink-0">
        <Icon className="h-6 w-6 text-accent" />
      </div>
      <div>
        <h2 className="text-xl font-semibold">{title}</h2>
        {subtitle ? (
          <p className="text-sm text-muted-foreground mt-1">{subtitle}</p>
        ) : null}
      </div>
    </div>
  );
}

interface HelpOverviewFeature {
  title: string;
  body: string;
}

function OverviewPanel({
  title,
  description,
  Icon,
  specsKey,
  featuresKey,
}: {
  title: string;
  description: string;
  Icon: React.ComponentType<{ className?: string }>;
  specsKey: string;
  featuresKey: string;
}) {
  const { t } = useTranslation();
  const features = t(featuresKey, {
    returnObjects: true,
  }) as HelpOverviewFeature[];

  return (
    <>
      <PanelHeader title={title} Icon={Icon} />
      <p className="text-sm text-muted-foreground leading-relaxed">
        {description}
      </p>
      <section aria-label={t('help.overview.featuresLabel')}>
        <h3 className="text-sm font-semibold text-muted-foreground mb-2">
          {t('help.overview.featuresLabel')}
        </h3>
        <div className="grid grid-cols-1 gap-2">
          {features.map((feature) => (
            <div
              key={feature.title}
              className="rounded-md border border-border px-3 py-2"
            >
              <div className="text-sm font-medium">{feature.title}</div>
              <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
                {feature.body}
              </p>
            </div>
          ))}
        </div>
      </section>
      <section aria-label={t('help.overview.specsLabel')}>
        <h3 className="text-sm font-semibold text-muted-foreground mb-2">
          {t('help.overview.specsLabel')}
        </h3>
        <SpecTable specsKey={specsKey} />
      </section>
      <TermsGrid terms={helpOverview.terms} />
    </>
  );
}

function FeaturePanel({ featureId }: { featureId: string }) {
  const { t } = useTranslation();
  const feature = getHelpFeature(featureId);
  const tutorial = feature.tutorialId
    ? getHelpTutorial(feature.tutorialId)
    : undefined;
  const Icon = feature.icon;

  return (
    <>
      <PanelHeader title={t(feature.titleKey)} Icon={Icon} />
      <p className="text-sm text-muted-foreground leading-relaxed">
        {t(feature.descriptionKey)}
      </p>
      <TermsGrid terms={feature.terms} />

      {tutorial ? (
        <section aria-label={t('help.relatedTutorial')}>
          <h3 className="text-sm font-semibold text-muted-foreground mb-2">
            {t('help.relatedTutorial')}
          </h3>
          <div className="flex items-center gap-3 rounded-md border border-border px-3 py-2">
            <tutorial.icon className="h-4 w-4 shrink-0 text-accent" />
            <div className="min-w-0">
              <div className="text-sm font-medium">
                {t('help.tutorialsSection')} {tutorial.index} —{' '}
                {t(tutorial.titleKey)}
              </div>
              <div className="text-xs text-muted-foreground truncate">
                {t(tutorial.subtitleKey)}
              </div>
            </div>
          </div>
        </section>
      ) : null}

      <Link to={feature.path}>
        <Button size="sm">
          {t('help.tutorialAction')}
          <ExternalLink className="h-4 w-4 ml-2" />
        </Button>
      </Link>
    </>
  );
}

function TutorialPanel({ tutorial }: { tutorial: HelpTutorial }) {
  const { t } = useTranslation();
  const steps = t(tutorial.stepsKey, {
    returnObjects: true,
  }) as { title: string; body: string }[];
  const specsLabel = tutorial.specsKey
    ? (t(`help.tutorials.${tutorial.id}.specsLabel`) as string)
    : null;

  return (
    <>
      <PanelHeader
        title={t(tutorial.titleKey)}
        subtitle={t(tutorial.subtitleKey)}
        Icon={tutorial.icon}
      />

      <div className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
        {t('help.tutorialsSection')} {tutorial.index}
      </div>

      {tutorial.specsKey && specsLabel ? (
        <section aria-label={specsLabel}>
          <h3 className="text-sm font-semibold text-muted-foreground mb-2">
            {specsLabel}
          </h3>
          <SpecTable specsKey={tutorial.specsKey} />
        </section>
      ) : null}

      <ol className="space-y-4">
        {steps.map((step, index) => (
          <li key={step.title} className="flex gap-3">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent/10 text-xs font-semibold text-accent">
              {index + 1}
            </span>
            <div>
              <h4 className="text-sm font-semibold">{step.title}</h4>
              <p className="text-sm text-muted-foreground mt-1 leading-relaxed">
                {step.body}
              </p>
            </div>
          </li>
        ))}
      </ol>

      <TermsGrid terms={tutorial.terms} />

      <Link to={tutorial.targetPath}>
        <Button size="sm">
          {t('help.tutorialAction')}
          <ExternalLink className="h-4 w-4 ml-2" />
        </Button>
      </Link>
    </>
  );
}
