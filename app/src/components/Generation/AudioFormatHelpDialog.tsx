import { Info } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';

/**
 * Help dialog documenting the audio output format menu (broadcast / CD / mp3)
 * specs and the recommended input-source quality. Triggered by the info icon
 * placed next to the output format selector in the generation box.
 */
export function AudioFormatHelpDialog() {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);

  const rows = [
    {
      key: 'broadcast',
      name: t('generation.outputFormat.options.broadcast'),
      sr: '48 kHz',
      bits: '24-bit PCM WAV',
      bitrate: '—',
      loudness: '-24 LUFS · TP ≤ -1.0 dBTP',
      channel: t('generation.outputFormat.help.dualMono'),
    },
    {
      key: 'cd',
      name: t('generation.outputFormat.options.cd'),
      sr: '44.1 kHz',
      bits: '16-bit PCM WAV',
      bitrate: '1,411 kbps',
      loudness: '—',
      channel: t('generation.outputFormat.help.dualMono'),
    },
    {
      key: 'mp3',
      name: t('generation.outputFormat.options.mp3'),
      sr: '44.1 kHz',
      bits: '192 kbps CBR',
      bitrate: '192 kbps',
      loudness: '-14 LUFS · TP ≤ -1.0 dBTP',
      channel: t('generation.outputFormat.help.dualMono'),
    },
  ];

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-8 w-8 shrink-0 rounded-full bg-card border border-border hover:bg-background/50 transition-all"
          aria-label={t('generation.outputFormat.helpIcon')}
        >
          <Info className="h-4 w-4" />
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t('generation.outputFormat.help.title')}</DialogTitle>
          <DialogDescription>
            {t('generation.outputFormat.help.description')}
          </DialogDescription>
        </DialogHeader>

        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border bg-muted/40 text-muted-foreground">
                <th className="px-3 py-2 text-left font-medium">{t('generation.outputFormat.help.colFormat')}</th>
                <th className="px-3 py-2 text-left font-medium">{t('generation.outputFormat.help.colSampleRate')}</th>
                <th className="px-3 py-2 text-left font-medium">{t('generation.outputFormat.help.colLoudness')}</th>
                <th className="px-3 py-2 text-left font-medium">{t('generation.outputFormat.help.colChannel')}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.key} className="border-b border-border/60 last:border-0">
                  <td className="px-3 py-2 font-medium">
                    <div>{row.name}</div>
                    <div className="text-muted-foreground">{row.bits}</div>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">{row.sr}</td>
                  <td className="px-3 py-2">{row.loudness}</td>
                  <td className="px-3 py-2">{row.channel}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="rounded-lg border border-accent/30 bg-accent/5 p-3 text-xs leading-relaxed text-muted-foreground">
          <p className="mb-1 font-medium text-foreground">
            {t('generation.outputFormat.help.inputTitle')}
          </p>
          <p>{t('generation.outputFormat.help.inputBody')}</p>
        </div>
      </DialogContent>
    </Dialog>
  );
}