import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Cloud, FolderSync, Loader2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { useToast } from '@/components/ui/use-toast';
import { apiClient } from '@/lib/api/client';
import { SettingRow, SettingSection } from './SettingRow';

// "Log in with Google Drive" OAuth pairing. The backend opens the system browser
// (reusing whatever Google account is already signed in; prompting if none),
// completes the code exchange, and stores a refresh token. Once linked, the app
// can back up captures and generations to a 'voicebox' folder in Drive forever
// without re-authorizing. The tokens never touch the frontend.
export function DriveSection() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [polling, setPolling] = useState(false);

  const { data: status } = useQuery({
    queryKey: ['drive-status'],
    queryFn: () => apiClient.getDriveStatus(),
    refetchInterval: polling ? 2000 : false,
  });

  const connected = status?.connected ?? false;

  // Once the browser flow completes, stop polling and celebrate.
  useEffect(() => {
    if (connected && polling) {
      setPolling(false);
      queryClient.invalidateQueries({ queryKey: ['drive-status'] });
      toast({
        title: t('settings.general.drive.connectedToastTitle'),
        description: t('settings.general.drive.connectedToastDescription', {
          email: status?.account_email ?? 'your Google account',
        }),
      });
    }
  }, [connected, polling, status?.account_email, t, toast, queryClient]);

  // Give up after two minutes so an abandoned browser flow doesn't leave the
  // button stuck on "Waiting for browser…".
  useEffect(() => {
    if (!polling) return;
    const timeoutId = window.setTimeout(() => {
      setPolling(false);
      toast({
        title: t('settings.general.drive.loginTimedOutTitle'),
        description: t('settings.general.drive.loginTimedOutDescription'),
        variant: 'destructive',
      });
    }, 120_000);
    return () => window.clearTimeout(timeoutId);
  }, [polling, t, toast]);

  const startLogin = useMutation({
    mutationFn: () => apiClient.startDriveLogin(),
    onSuccess: () => {
      setPolling(true);
      toast({
        title: t('settings.general.drive.loginContinueTitle'),
        description: t('settings.general.drive.loginContinueDescription'),
      });
    },
    onError: (error: Error) => {
      const notConfigured =
        /GOOGLE_CLIENT_ID is not configured|not configured/i.test(error.message);
      toast({
        title: notConfigured
          ? t('settings.general.drive.notConfiguredTitle')
          : t('settings.general.drive.loginFailedTitle'),
        description: notConfigured
          ? t('settings.general.drive.notConfiguredDescription')
          : error.message,
        variant: 'destructive',
      });
    },
  });

  const backup = useMutation({
    mutationFn: () => apiClient.runDriveBackup(),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['drive-status'] });
      toast({
        title: result.success
          ? t('settings.general.drive.backupSuccessTitle')
          : t('settings.general.drive.backupFailedTitle'),
        description: result.message,
        variant: result.success ? 'default' : 'destructive',
      });
    },
    onError: (error: Error) =>
      toast({
        title: t('settings.general.drive.backupFailedTitle'),
        description: error.message,
        variant: 'destructive',
      }),
  });

  const disconnect = useMutation({
    mutationFn: () => apiClient.disconnectDrive(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['drive-status'] });
      toast({
        title: t('settings.general.drive.disconnectedTitle'),
        description: t('settings.general.drive.disconnectedDescription'),
      });
    },
    onError: (error: Error) =>
      toast({
        title: t('settings.general.drive.disconnectFailedTitle'),
        description: error.message,
        variant: 'destructive',
      }),
  });

  const busy = startLogin.isPending || polling;

  const backupInfo = status?.last_backup_at
    ? t('settings.general.drive.lastBackup', { time: new Date(status.last_backup_at).toLocaleString() })
    : '';

  return (
    <SettingSection
      title={t('settings.general.drive.sectionTitle')}
      description={t('settings.general.drive.sectionDescription')}
    >
      <SettingRow
        title={connected ? t('settings.general.drive.connectedTitle') : t('settings.general.drive.accountTitle')}
        description={
          connected
            ? t('settings.general.drive.connectedDescription', {
                email: status?.account_email ?? 'your Google account',
                backupInfo,
              })
            : t('settings.general.drive.notConnectedDescription')
        }
        action={
          connected ? (
            <div className="flex gap-2">
              <Button disabled={busy} onClick={() => backup.mutate()} size="sm" variant="outline">
                {backup.isPending ? (
                  <>
                    <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                    {t('settings.general.drive.backingUp')}
                  </>
                ) : (
                  <>
                    <FolderSync className="h-3.5 w-3.5 mr-1.5" />
                    {t('settings.general.drive.backupButton')}
                  </>
                )}
              </Button>
              <Button
                disabled={disconnect.isPending}
                onClick={() => disconnect.mutate()}
                size="sm"
                variant="outline"
              >
                {disconnect.isPending ? (
                  <>
                    <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                    {t('settings.general.drive.disconnecting')}
                  </>
                ) : (
                  t('settings.general.drive.disconnectButton')
                )}
              </Button>
            </div>
          ) : (
            <Button disabled={busy} onClick={() => startLogin.mutate()} size="sm">
              {busy ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                  {polling
                    ? t('settings.general.drive.loginWaiting')
                    : t('settings.general.drive.loginOpening')}
                </>
              ) : (
                <>
                  <Cloud className="h-3.5 w-3.5 mr-1.5" />
                  {t('settings.general.drive.loginButton')}
                </>
              )}
            </Button>
          )
        }
      />

      {connected && (
        <SettingRow
          title={t('settings.general.drive.backupScopeTitle')}
          description={t('settings.general.drive.backupScopeDescription')}
        />
      )}
    </SettingSection>
  );
}