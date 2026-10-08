import { useSession } from "./session";
import { useTheme, type ThemeChoice } from "./theme";
import { Icon, type IconName } from "../shared/ui/Icon";
import { patchMe } from "../shared/api/endpoints";

const options: [ThemeChoice, IconName, string][] = [
  ["light", "sun", "Светлая тема"],
  ["dark", "moon", "Тёмная тема"],
  ["system", "system", "Системная тема"],
];

export function ThemeSwitch() {
  const [choice, setChoice] = useTheme();
  const { me, updateMe } = useSession();
  function pick(c: ThemeChoice) {
    setChoice(c);
    // Persist to the profile when signed in; the local choice applies immediately.
    if (me && me.theme !== c) patchMe({ theme: c }).then(updateMe, () => {});
  }
  return (
    <div className="theme-switch" role="group" aria-label="Тема оформления">
      {options.map(([value, icon, label]) => (
        <button
          key={value}
          type="button"
          aria-pressed={choice === value}
          aria-label={label}
          title={label}
          onClick={() => pick(value)}
        >
          <Icon name={icon} size={20} />
        </button>
      ))}
    </div>
  );
}
