import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2, RotateCcw } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useToast } from '@/components/ui/use-toast';
import { apiClient } from '@/lib/api/client';
import type { ChunkMeta } from '@/lib/api/types';
import { formatAudioDuration } from '@/lib/utils/audio';
import { cn } from '@/lib/utils/cn';
import { useGenerationStore } from '@/stores/generationStore';
import { usePlayerStore } from '@/stores/playerStore';

interface ChunkEditorProps {
  duration: number;
}

function timeToPct(ms: number, durationSec: number): number {
  if (!durationSec || durationSec <= 0) return 0;
  return Math.min(100, Math.max(0, (ms / 1000 / durationSec) * 100));
}

/**
 * Sentence-chunk editor for the currently playing generation.
 *
 * Draws chunk boundary markers over the waveform and lists each sentence as
 * a selectable chip. Selecting a chip lets the user correct the sentence text
 * and regenerate just that segment; the result is spliced back in as a new
 * version on the backend.
 */
export function ChunkEditor({ duration }: ChunkEditorProps) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const audioId = usePlayerStore((s) => s.audioId);
  const profileId = usePlayerStore((s) => s.profileId);
  const title = usePlayerStore((s) => s.title);
  const selectedChunkIndex = usePlayerStore((s) => s.selectedChunkIndex);
  const setSelectedChunkIndex = usePlayerStore((s) => s.setSelectedChunkIndex);
  const setAudioWithAutoPlay = usePlayerStore((s) => s.setAudioWithAutoPlay);
  const pendingGenerationIds = useGenerationStore((s) => s.pendingGenerationIds);
  const addPendingGeneration = useGenerationStore((s) => s.addPendingGeneration);

  const [textOverride, setTextOverride] = useState('');
  const [seed, setSeed] = useState('');
  const [isRegenerating, setIsRegenerating] = useState(false);
  const initiatedRegenRef = useRef(false);

  // Real generations only (preview IDs like "preview-<ts>" have no chunks).
  const isGeneration = !!audioId && !audioId.startsWith('preview-');

  const { data: generation, refetch } = useQuery({
    queryKey: ['generation', audioId],
    queryFn: () => apiClient.getGeneration(audioId as string),
    enabled: isGeneration,
    staleTime: 5_000,
  });

  const chunks: ChunkMeta[] = generation?.chunks ?? [];
  const selectedChunk =
    selectedChunkIndex !== null && selectedChunkIndex < chunks.length
      ? chunks[selectedChunkIndex]
      : null;

  // Prefill the text override whenever a different chunk is selected.
  // biome-ignore lint/correctness/useExhaustiveDependencies: prefill only on chunk/audio switch
  useEffect(() => {
    setTextOverride(selectedChunk?.text ?? '');
    setSeed('');
  }, [selectedChunkIndex, audioId]);

  // When a chunk regeneration finishes (the id leaves the pending set),
  // reload the player with the new default-version audio.
  const isPending = !!audioId && pendingGenerationIds.has(audioId);
  // biome-ignore lint/correctness/useExhaustiveDependencies: stable refs; triggers only on pending/audio switch
  useEffect(() => {
    if (!initiatedRegenRef.current || isPending || !audioId) return;
    initiatedRegenRef.current = false;
    setIsRegenerating(false);

    const reload = async () => {
      const result = await refetch();
      const status = result.data?.status;
      if (status === 'completed') {
        queryClient.refetchQueries({ queryKey: ['history'] });
        const url = `${apiClient.getAudioUrl(audioId)}?v=${Date.now()}`;
        setAudioWithAutoPlay(url, audioId, profileId, title ?? undefined);
        toast({
          title: t('chunkEditor.completedTitle'),
          description: t('chunkEditor.completedDescription'),
        });
      } else if (status === 'failed') {
        toast({
          title: t('chunkEditor.failedTitle'),
          description: t('chunkEditor.failedDescription'),
          variant: 'destructive',
        });
      }
    };
    reload();
  }, [isPending, audioId]);

  if (!isGeneration || chunks.length === 0) {
    return null;
  }

  const handleRegenerate = async () => {
    if (!audioId || selectedChunkIndex === null) return;
    const text = textOverride.trim();
    setIsRegenerating(true);
    initiatedRegenRef.current = true;
    try {
      await apiClient.regenerateChunk(audioId, selectedChunkIndex, {
        text_override: text && text !== selectedChunk?.text ? text : undefined,
        seed: seed ? Number(seed) : undefined,
      });
      addPendingGeneration(audioId);
    } catch (error) {
      initiatedRegenRef.current = false;
      setIsRegenerating(false);
      toast({
        title: t('chunkEditor.failedTitle'),
        description: error instanceof Error ? error.message : t('common.unknownError'),
        variant: 'destructive',
      });
    }
  };

  return (
    <div className="flex flex-col gap-2 pt-2 select-none">
      {/* Waveform markers */}
      <div className="relative h-6 -mt-1">
        {chunks.map((chunk, i) => {
          const left = timeToPct(chunk.start_ms, duration);
          const width = Math.max(
            1.5,
            timeToPct(chunk.end_ms, duration) - left,
          );
          const isSelected = selectedChunkIndex === i;
          return (
            <button
              key={chunk.index}
              type="button"
              onClick={() => setSelectedChunkIndex(isSelected ? null : i)}
              className={cn(
                'absolute top-0 bottom-0 rounded-sm transition-colors cursor-pointer',
                isSelected
                  ? 'bg-accent/60 ring-1 ring-accent'
                  : 'bg-muted/60 hover:bg-accent/30',
              )}
              style={{ left: `${left}%`, width: `${width}%` }}
              title={chunk.text}
              aria-label={`${t('chunkEditor.sentence', { n: i + 1 })}, ${formatAudioDuration(chunk.start_ms / 1000)}`}
            />
          );
        })}
      </div>

      {/* Chunk chips */}
      <div className="flex items-center gap-1.5 overflow-x-auto pb-0.5">
        {chunks.map((chunk, i) => (
          <button
            key={chunk.index}
            type="button"
            onClick={() => setSelectedChunkIndex(selectedChunkIndex === i ? null : i)}
            className={cn(
              'shrink-0 text-xs px-2 py-1 rounded-full border transition-colors max-w-[220px]',
              selectedChunkIndex === i
                ? 'bg-accent text-accent-foreground border-accent'
                : 'bg-background text-muted-foreground border-border hover:bg-muted/50',
            )}
            title={chunk.text}
          >
            <span className="font-medium">{i + 1}</span>
            <span className="mx-1 text-muted-foreground/70">·</span>
            <span className="truncate">{chunk.text}</span>
          </button>
        ))}
      </div>

      {/* Edit panel */}
      {selectedChunk !== null && (
        <div className="flex flex-col gap-2 border-t pt-2">
          <div className="flex items-center justify-between gap-2">
            <Label className="text-xs font-medium text-muted-foreground shrink-0">
              {t('chunkEditor.sentenceLabel', { n: selectedChunkIndex! + 1 })}
            </Label>
            <span className="text-xs font-mono text-muted-foreground shrink-0">
              {formatAudioDuration(selectedChunk.start_ms / 1000)} –{' '}
              {formatAudioDuration(selectedChunk.end_ms / 1000)}
            </span>
          </div>
          <Input
            value={textOverride}
            onChange={(e) => setTextOverride(e.target.value)}
            placeholder={t('chunkEditor.textPlaceholder')}
            className="h-8 text-sm"
          />
          <div className="flex items-center gap-2">
            <Input
              value={seed}
              onChange={(e) => setSeed(e.target.value)}
              type="number"
              min={0}
              step={1}
              placeholder={t('chunkEditor.seedPlaceholder')}
              className="h-8 text-sm w-36"
            />
            <Button
              size="sm"
              className="ml-auto"
              onClick={handleRegenerate}
              disabled={isRegenerating}
            >
              {isRegenerating ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <RotateCcw className="h-4 w-4 mr-2" />
              )}
              {t('chunkEditor.regenerateAction')}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
