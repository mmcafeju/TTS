import {
  AudioLines,
  Loader2,
  Play,
  Trash2,
  Upload,
  Wand2,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Progress } from '@/components/ui/progress';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { apiClient } from '@/lib/api/client';
import type { VCModelResponse } from '@/lib/api/types';
import { cn } from '@/lib/utils/cn';
import {
  useConvertVC,
  useDeleteVCModel,
  useTrainVC,
  useUploadVC,
  useVCJob,
  useVCJobs,
  useVCModels,
  useVCStatus,
} from '@/lib/hooks/useVC';

const JOB_STATUS_LABELS: Record<string, string> = {
  pending: 'jobs.pending',
  running: 'jobs.running',
  done: 'jobs.done',
  failed: 'jobs.failed',
  cancelled: 'jobs.cancelled',
};

const MODEL_STATUS_LABELS: Record<string, string> = {
  ready: 'models.ready',
  training: 'models.training',
  failed: 'models.failed',
};

export function VCTab() {
  const { t } = useTranslation();
  const { data: status } = useVCStatus();
  const { data: models = [] } = useVCModels();
  const { data: jobs = [] } = useVCJobs(10);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);

  // Track the most recent running/pending job to poll progress.
  const runningJob = useMemo(
    () => jobs.find((j) => j.status === 'running' || j.status === 'pending') ?? null,
    [jobs],
  );
  const polledJob = useVCJob(activeJobId ?? runningJob?.id ?? null);
  const activeJob = polledJob.data ?? runningJob;

  const trainMutation = useTrainVC();
  const convertMutation = useConvertVC();

  const [trainName, setTrainName] = useState('');
  const [trainFiles, setTrainFiles] = useState<File[]>([]);
  const [sampleRate, setSampleRate] = useState('40000');
  const [epochs, setEpochs] = useState('100');
  const [batchSize, setBatchSize] = useState('4');
  const [f0Method, setF0Method] = useState('rmvpe');

  const [convertModelId, setConvertModelId] = useState('');
  const [convertFiles, setConvertFiles] = useState<File[]>([]);
  const [indexRate, setIndexRate] = useState('0.75');
  const [pitch, setPitch] = useState('0');
  const [convertF0, setConvertF0] = useState('rmvpe');

  // Select first ready model for the convert panel once models load.
  useEffect(() => {
    if (!convertModelId) {
      const firstReady = models.find((m) => m.status === 'ready');
      if (firstReady) setConvertModelId(firstReady.id);
    }
  }, [models, convertModelId]);

  const uploadMutation = useUploadVC();
  const deleteModel = useDeleteVCModel();

  const handleDatasetFiles = (e: React.ChangeEvent<HTMLInputElement>) => {
    setTrainFiles(Array.from(e.target.files ?? []));
  };

  const handleSourceFiles = (e: React.ChangeEvent<HTMLInputElement>) => {
    setConvertFiles(Array.from(e.target.files ?? []));
  };

  const handleTrain = async () => {
    if (!trainName.trim() || trainFiles.length === 0) return;
    try {
      const uploaded = [];
      for (const file of trainFiles) {
        const res = await uploadMutation.mutateAsync({ file, purpose: 'dataset' });
        uploaded.push(res.file_id);
      }
      await trainMutation.mutateAsync({
        name: trainName.trim(),
        file_ids: uploaded,
        sample_rate: Number(sampleRate),
        total_epochs: Number(epochs),
        batch_size: Number(batchSize),
        f0_method: f0Method as 'rmvpe' | 'harvest',
      });
      setTrainName('');
      setTrainFiles([]);
    } catch (err) {
      console.error('Failed to start training:', err);
    }
  };

  const handleConvert = async () => {
    if (!convertModelId || convertFiles.length === 0) return;
    try {
      const uploaded = [];
      for (const file of convertFiles) {
        const res = await uploadMutation.mutateAsync({ file, purpose: 'source' });
        uploaded.push(res.file_id);
      }
      const job = await convertMutation.mutateAsync({
        model_id: convertModelId,
        file_id: uploaded[0],
        f0_method: convertF0 as 'rmvpe' | 'harvest',
        index_rate: Number(indexRate),
        pitch: Number(pitch),
      });
      setActiveJobId(job.id);
      setConvertFiles([]);
    } catch (err) {
      console.error('Failed to start conversion:', err);
    }
  };

  return (
    <div className="h-full overflow-y-auto">
      <div className="flex items-center gap-3 mb-6">
        <h1 className="text-2xl font-bold">{t('vc.title')}</h1>
        <div className="flex-1" />
        <Badge variant={status?.engine_ready ? 'secondary' : 'destructive'}>
          {status?.engine_ready
            ? t('vc.engineReady', { device: status.device_name ?? 'GPU' })
            : t('vc.engineNotReady')}
        </Badge>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* ── Train panel ─────────────────────────────────────────────── */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Wand2 className="h-4 w-4" />
              {t('vc.train.title')}
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="vc-train-name">{t('vc.train.modelName')}</Label>
              <Input
                id="vc-train-name"
                value={trainName}
                onChange={(e) => setTrainName(e.target.value)}
                placeholder={t('vc.train.modelNamePlaceholder')}
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <Label>{t('vc.train.dataset')}</Label>
              <label className="flex cursor-pointer items-center justify-center gap-2 rounded-md border border-dashed p-4 text-sm text-muted-foreground hover:bg-muted/50">
                <Upload className="h-4 w-4" />
                {trainFiles.length > 0
                  ? t('vc.train.filesSelected', { count: trainFiles.length })
                  : t('vc.train.selectFiles')}
                <input
                  type="file"
                  accept="audio/*"
                  multiple
                  className="hidden"
                  onChange={handleDatasetFiles}
                />
              </label>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1.5">
                <Label>{t('vc.train.sampleRate')}</Label>
                <Select value={sampleRate} onValueChange={setSampleRate}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="32000">32 kHz</SelectItem>
                    <SelectItem value="40000">40 kHz</SelectItem>
                    <SelectItem value="48000">48 kHz</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label>{t('vc.train.f0Method')}</Label>
                <Select value={f0Method} onValueChange={setF0Method}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="rmvpe">RMVPE</SelectItem>
                    <SelectItem value="harvest">Harvest</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label>{t('vc.train.epochs')}</Label>
                <Input
                  type="number"
                  min={1}
                  max={1000}
                  value={epochs}
                  onChange={(e) => setEpochs(e.target.value)}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label>{t('vc.train.batchSize')}</Label>
                <Input
                  type="number"
                  min={1}
                  max={4}
                  value={batchSize}
                  onChange={(e) => setBatchSize(e.target.value)}
                />
              </div>
            </div>

            <Button
              onClick={handleTrain}
              disabled={
                trainMutation.isPending ||
                uploadMutation.isPending ||
                !trainName.trim() ||
                trainFiles.length === 0 ||
                !status?.can_train
              }
            >
              {(trainMutation.isPending || uploadMutation.isPending) && (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              )}
              {t('vc.train.start')}
            </Button>
            {!status?.can_train && (
              <p className="text-xs text-destructive">{t('vc.train.noVram')}</p>
            )}
          </CardContent>
        </Card>

        {/* ── Convert panel ───────────────────────────────────────────── */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <AudioLines className="h-4 w-4" />
              {t('vc.convert.title')}
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label>{t('vc.convert.model')}</Label>
              <Select value={convertModelId} onValueChange={setConvertModelId}>
                <SelectTrigger>
                  <SelectValue placeholder={t('vc.convert.selectModel')} />
                </SelectTrigger>
                <SelectContent>
                  {models
                    .filter((m) => m.status === 'ready')
                    .map((m) => (
                      <SelectItem key={m.id} value={m.id}>
                        {m.name} ({m.sample_rate / 1000}k)
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </div>

            <div className="flex flex-col gap-1.5">
              <Label>{t('vc.convert.source')}</Label>
              <label className="flex cursor-pointer items-center justify-center gap-2 rounded-md border border-dashed p-4 text-sm text-muted-foreground hover:bg-muted/50">
                <Upload className="h-4 w-4" />
                {convertFiles.length > 0
                  ? t('vc.convert.filesSelected', { count: convertFiles.length })
                  : t('vc.convert.selectFiles')}
                <input
                  type="file"
                  accept="audio/*"
                  multiple
                  className="hidden"
                  onChange={handleSourceFiles}
                />
              </label>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1.5">
                <Label>{t('vc.convert.f0Method')}</Label>
                <Select value={convertF0} onValueChange={setConvertF0}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="rmvpe">RMVPE</SelectItem>
                    <SelectItem value="harvest">Harvest</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label>{t('vc.convert.indexRate')}</Label>
                <Input
                  type="number"
                  min={0}
                  max={1}
                  step={0.05}
                  value={indexRate}
                  onChange={(e) => setIndexRate(e.target.value)}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label>{t('vc.convert.pitch')}</Label>
                <Input
                  type="number"
                  min={-24}
                  max={24}
                  value={pitch}
                  onChange={(e) => setPitch(e.target.value)}
                />
              </div>
            </div>

            <Button
              onClick={handleConvert}
              disabled={
                convertMutation.isPending ||
                uploadMutation.isPending ||
                !convertModelId ||
                convertFiles.length === 0 ||
                !status?.can_convert
              }
            >
              {(convertMutation.isPending || uploadMutation.isPending) && (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              )}
              {t('vc.convert.start')}
            </Button>
            {!status?.can_convert && (
              <p className="text-xs text-destructive">{t('vc.convert.noVram')}</p>
            )}

            {activeJob && (
              <div className="flex flex-col gap-2 rounded-md border p-3">
                <div className="flex items-center gap-2 text-sm">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  <span>
                    {t('vc.convert.jobProgress', {
                      stage: activeJob.stage ?? activeJob.status,
                      pct: Math.round(activeJob.progress),
                    })}
                  </span>
                </div>
                <Progress value={activeJob.progress} />
                {activeJob.status === 'done' && activeJob.result_path && (
                  <a
                    href={apiClient.getVCResultUrl(activeJob.id)}
                    target="_blank"
                    rel="noreferrer"
                    className="flex items-center gap-1.5 text-sm text-accent hover:underline"
                  >
                    <Play className="h-3.5 w-3.5" />
                    {t('vc.convert.listenResult')}
                  </a>
                )}
                {activeJob.error && (
                  <p className="text-xs text-destructive">{activeJob.error}</p>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* ── Models table ─────────────────────────────────────────────── */}
      <Card className="mt-6">
        <CardHeader>
          <CardTitle>{t('vc.models.title')}</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('vc.models.name')}</TableHead>
                <TableHead>{t('vc.models.status')}</TableHead>
                <TableHead>{t('vc.models.sampleRate')}</TableHead>
                <TableHead>{t('vc.models.epochs')}</TableHead>
                <TableHead>{t('vc.models.created')}</TableHead>
                <TableHead className="w-6" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {models.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-muted-foreground">
                    {t('vc.models.empty')}
                  </TableCell>
                </TableRow>
              )}
              {models.map((model) => (
                <ModelRow
                  key={model.id}
                  model={model}
                  onDelete={() => deleteModel.mutate(model.id)}
                  deleting={deleteModel.isPending}
                />
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* ── Jobs history ─────────────────────────────────────────────── */}
      <Card className="mt-6 mb-8">
        <CardHeader>
          <CardTitle>{t('vc.jobs.title')}</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('vc.jobs.kind')}</TableHead>
                <TableHead>{t('vc.jobs.status')}</TableHead>
                <TableHead>{t('vc.jobs.progress')}</TableHead>
                <TableHead>{t('vc.jobs.stage')}</TableHead>
                <TableHead>{t('vc.jobs.created')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {jobs.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-muted-foreground">
                    {t('vc.jobs.empty')}
                  </TableCell>
                </TableRow>
              )}
              {jobs.map((job) => (
                <TableRow key={job.id}>
                  <TableCell className="capitalize">{job.kind}</TableCell>
                  <TableCell>
                    <span
                      className={cn(
                        'inline-flex items-center gap-1.5',
                        job.status === 'failed'
                          ? 'text-destructive'
                          : job.status === 'done'
                            ? 'text-accent'
                            : 'text-muted-foreground',
                      )}
                    >
                      {job.status === 'running' && (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      )}
                      {t(JOB_STATUS_LABELS[job.status] ?? job.status)}
                    </span>
                  </TableCell>
                  <TableCell>{Math.round(job.progress)}%</TableCell>
                  <TableCell className="text-muted-foreground">{job.stage ?? '—'}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {job.created_at
                      ? new Date(job.created_at).toLocaleString()
                      : '—'}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

function ModelRow({
  model,
  onDelete,
  deleting,
}: {
  model: VCModelResponse;
  onDelete: () => void;
  deleting: boolean;
}) {
  const { t } = useTranslation();

  return (
    <TableRow>
      <TableCell className="font-medium">{model.name}</TableCell>
      <TableCell>
        <span
          className={cn(
            'inline-flex items-center gap-1.5',
            model.status === 'failed'
              ? 'text-destructive'
              : model.status === 'ready'
                ? 'text-accent'
                : 'text-muted-foreground',
          )}
        >
          {model.status === 'training' && <Loader2 className="h-3 w-3 animate-spin" />}
          {t(MODEL_STATUS_LABELS[model.status] ?? model.status)}
        </span>
        {model.error && (
          <span className="ml-2 text-xs text-destructive">{model.error}</span>
        )}
      </TableCell>
      <TableCell>{model.sample_rate / 1000} kHz</TableCell>
      <TableCell>{model.total_epochs ?? '—'}</TableCell>
      <TableCell className="text-muted-foreground">
        {model.created_at ? new Date(model.created_at).toLocaleString() : '—'}
      </TableCell>
      <TableCell>
        <Button
          variant="ghost"
          size="icon"
          onClick={onDelete}
          disabled={deleting}
          aria-label={t('common.delete')}
        >
          <Trash2 className="h-4 w-4 text-destructive" />
        </Button>
      </TableCell>
    </TableRow>
  );
}