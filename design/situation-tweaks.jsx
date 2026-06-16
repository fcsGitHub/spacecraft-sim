/* Tweaks 面板 — 态势页可调参数 */
const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "accentColor": "#4a7fd4",
  "showLabels": true,
  "trailMin": 20,
  "orbitOpacity": 0.55
}/*EDITMODE-END*/;

function SitTweaksApp() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);

  React.useEffect(() => {
    if (window.SitMain) {
      window.SitMain.setAccent(t.accentColor);
      window.SitMain.setTweaks({
        labels: t.showLabels,
        trailSec: t.trailMin * 60,
        orbitOpacity: t.orbitOpacity
      });
    }
  }, [t]);

  return (
    <TweaksPanel>
      <TweakSection label="主题" />
      <TweakColor label="强调色" value={t.accentColor}
        options={['#4a7fd4', '#3fb5ad', '#d9a13f', '#9b7fd4']}
        onChange={(v) => setTweak('accentColor', v)} />
      <TweakSection label="三维显示" />
      <TweakToggle label="实体标签" value={t.showLabels}
        onChange={(v) => setTweak('showLabels', v)} />
      <TweakSlider label="轨迹长度" value={t.trailMin} min={2} max={90} step={1} unit="min"
        onChange={(v) => setTweak('trailMin', v)} />
      <TweakSlider label="轨道线浓度" value={t.orbitOpacity} min={0.1} max={1} step={0.05}
        onChange={(v) => setTweak('orbitOpacity', v)} />
    </TweaksPanel>
  );
}

ReactDOM.createRoot(document.getElementById('tweaks-root')).render(<SitTweaksApp />);
