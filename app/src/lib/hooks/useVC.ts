import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/lib/api/client';
import type { VCConvertRequest, VCTrainRequest } from '@/lib/api/types';

export function useVCStatus() {
  return useQuery({
    queryKey: ['vc', 'status'],
    queryFn: () => apiClient.getVCStatus(),
    refetchInterval: 15000,
  });
}

export function useVCModels() {
  return useQuery({
    queryKey: ['vc', 'models'],
    queryFn: () => apiClient.listVCModels(),
  });
}

export function useVCJobs(limit = 20) {
  return useQuery({
    queryKey: ['vc', 'jobs', limit],
    queryFn: () => apiClient.listVCJobs(limit),
  });
}

export function useVCJob(jobId: string | null) {
  return useQuery({
    queryKey: ['vc', 'job', jobId],
    queryFn: () => apiClient.getVCJob(jobId as string),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const job = query.state.data;
      return job && ['done', 'failed', 'cancelled'].includes(job.status) ? false : 3000;
    },
  });
}

export function useUploadVC() {
  return useMutation({
    mutationFn: ({ file, purpose }: { file: File; purpose: 'dataset' | 'source' }) =>
      apiClient.uploadVC(file, purpose),
  });
}

export function useTrainVC() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: VCTrainRequest) => apiClient.trainVC(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vc', 'models'] });
      queryClient.invalidateQueries({ queryKey: ['vc', 'jobs'] });
    },
  });
}

export function useConvertVC() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: VCConvertRequest) => apiClient.convertVC(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vc', 'jobs'] });
    },
  });
}

export function useDeleteVCModel() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (modelId: string) => apiClient.deleteVCModel(modelId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vc', 'models'] });
    },
  });
}