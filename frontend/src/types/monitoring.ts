export interface GrabberControls {
  start: () => void;
  stop: () => void;
  getIsRunning: () => boolean;
}
