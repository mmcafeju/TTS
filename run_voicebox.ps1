# Voicebox launcher
$ErrorActionPreference = 'SilentlyContinue'

$Root = 'D:\TTS'
$Port = 17493
$Url = "http://127.0.0.1:$Port"
$Health = "$Url/health"
$BootTimeoutSec = 120

# Open the app in a standalone window (no browser tabs/address bar). Falls
# back to a normal browser tab if neither Edge nor Chrome is present.
function Open-InteractiveApp {
    $candidates = @(
        "$env:ProgramFiles (x86)\Microsoft\Edge\Application\msedge.exe",
        "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
        "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
        "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($candidates) {
        Start-Process -FilePath $candidates -ArgumentList "--app=$Url"
    } else {
        Start-Process $Url
    }
}

$running = $true
try { Invoke-WebRequest -Uri $Health -UseBasicParsing -TimeoutSec 2 | Out-Null }
catch { $running = $false }

if ($running) {
    Open-InteractiveApp
    exit 0
}

$serverProcess = $null
try {
    $serverProcess = Start-Process -FilePath 'python' `
        -ArgumentList '-m','uvicorn','backend.main:app','--host','127.0.0.1','--port',"$Port" `
        -WorkingDirectory $Root -WindowStyle Hidden -PassThru
} catch {
    $serverProcess = $null
}

# Splash with rotating spinner + indeterminate bar while the server boots.
Add-Type -AssemblyName PresentationFramework

$xaml = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Voicebox" Height="230" Width="360" WindowStyle="None"
        AllowsTransparency="True" Background="Transparent" ResizeMode="NoResize"
        WindowStartupLocation="CenterScreen" Topmost="True" ShowInTaskbar="True">
  <Border CornerRadius="20" Background="#1B1836" Padding="28,22"
          BorderBrush="#3A3570" BorderThickness="1">
    <Border.Effect>
      <DropShadowEffect BlurRadius="28" ShadowDepth="0" Opacity="0.45" Color="#000000"/>
    </Border.Effect>
    <StackPanel>
      <Grid HorizontalAlignment="Center" Width="52" Height="52">
        <Ellipse x:Name="SpinnerArc" Width="52" Height="52"
                 Stroke="#818CF8" StrokeThickness="5"
                 StrokeDashArray="0.55 0.85">
          <Ellipse.RenderTransform>
            <RotateTransform x:Name="SpinnerRotate" Angle="0" CenterX="26" CenterY="26"/>
          </Ellipse.RenderTransform>
        </Ellipse>
        <Ellipse Width="52" Height="52" Stroke="#FFFFFF" StrokeThickness="5" Opacity="0.10"/>
      </Grid>
      <TextBlock x:Name="StatusText" Text="Voicebox 시작 중…" Foreground="#FFFFFF"
                 FontSize="15" FontFamily="Malgun Gothic" TextAlignment="Center"
                 HorizontalAlignment="Center" Margin="0,16,0,0" FontWeight="SemiBold"/>
      <TextBlock x:Name="SubText" Foreground="#A6A9C9" FontSize="11"
                 FontFamily="Malgun Gothic" TextAlignment="Center"
                 HorizontalAlignment="Center" Margin="0,5,0,0"/>
      <ProgressBar Height="6" Margin="8,16,8,0" IsIndeterminate="True"
                   Foreground="#818CF8" Background="#2B2850" BorderThickness="0"
                   Opacity="0.9"/>
    </StackPanel>
  </Border>
</Window>
'@

$xml = New-Object System.Xml.XmlDocument
$xml.LoadXml($xaml)
$reader = New-Object System.Xml.XmlNodeReader $xml
$window = [System.Windows.Markup.XamlReader]::Load($reader)
$window.Hide() | Out-Null

$spinnerRotate = $window.FindName('SpinnerRotate')
$statusText = $window.FindName('StatusText')
$subText = $window.FindName('SubText')

$script:ready = $false
$script:failed = $false
$script:pollCount = 0
$script:serverProcess = $serverProcess
$script:deadline = [DateTime]::Now.AddSeconds($BootTimeoutSec)

$anim = New-Object System.Windows.Media.DoubleAnimation
$anim.From = 0
$anim.To = 360
$anim.Duration = [System.Windows.Duration]::new([TimeSpan]::FromSeconds(1.1))
$anim.RepeatBehavior = [System.Windows.Media.RepeatBehavior]::Forever
$spinnerRotate.BeginAnimation([System.Windows.Media.RotateTransform]::AngleProperty, $anim)

$subText.Text = 'TTS 엔진을 불러오는 중입니다'
$window.Show()

$timer = New-Object System.Windows.Threading.DispatcherTimer
$timer.Interval = [TimeSpan]::FromMilliseconds(500)
$timer.Add_Tick({
    if ($script:serverProcess -and $script:serverProcess.HasExited) {
        $script:failed = $true
        $statusText.Text = '시작하지 못했습니다'
        $subText.Text = 'Python 의존성이 설치되었는지 확인해주세요.'
        $timer.Stop()
        Start-Sleep -Seconds 4
        $window.Close()
        return
    }
    if ([DateTime]::Now -gt $script:deadline) {
        $script:failed = $true
        $statusText.Text = '시작하지 못했습니다'
        $subText.Text = '요청 시간이 초과되었습니다. 로그를 확인해주세요.'
        $timer.Stop()
        Start-Sleep -Seconds 4
        $window.Close()
        return
    }
    try {
        Invoke-WebRequest -Uri $Health -UseBasicParsing -TimeoutSec 2 | Out-Null
        $script:ready = $true
        $timer.Stop()
        $statusText.Text = '준비 완료'
        $subText.Text = '앱을 여는 중…'
        Start-Sleep -Milliseconds 400
        $window.Close()
    } catch {
        $script:pollCount++
        $subText.Text = "서버 준비 중… ($($script:pollCount))"
    }
})
$timer.Start()

$app = New-Object System.Windows.Application
$app.Run($window) | Out-Null
$timer.Stop()

if (-not $script:failed) {
    Open-InteractiveApp
} else {
    exit 1
}