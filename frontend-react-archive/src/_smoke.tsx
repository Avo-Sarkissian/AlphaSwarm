// DEV-ONLY smoke harness: eagerly references each ported component so Vite / tsc
// surface ReferenceErrors, missing imports, and type holes that would otherwise stay
// hidden until Wave 2 mounts them. NEVER import this from a production code path.
import * as AppV2  from './components/app_v2';
import * as AppRef from './components/app';
import * as Viz    from './components/viz';
import * as Pan    from './components/panels';
import * as Mod    from './components/modals';
import * as Set    from './components/settings';
import * as Hist   from './components/history';
import * as Twe    from './components/tweaks';
import * as Sta    from './components/states';
import * as Ico    from './components/icons';
import * as V2     from './components/v2';

// Force the bundler + tsc to keep every symbol live.
export const __SMOKE__ = { AppV2, AppRef, Viz, Pan, Mod, Set, Hist, Twe, Sta, Ico, V2 };
