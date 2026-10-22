// The report modal keeps polling only while the backend says this cycle's report
// job is running; every other answer ends the poll and is shown to the user.
export function shouldKeepPolling(detail: { status: number; code: string | null }): boolean {
  return detail.code === 'report_generation_in_progress';
}
