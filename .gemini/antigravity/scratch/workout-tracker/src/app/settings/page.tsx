'use client';

import { PageLayout } from '@/components/ui/PageLayout';
import { DEV_USER_ID } from '@/lib/constants';
import { Copy } from 'lucide-react';

export default function SettingsPage() {
    return (
        <PageLayout title="Settings">
            <div className="space-y-6">
                <section className="bg-card border border-border rounded-xl p-4">
                    <h3 className="font-semibold mb-2">Account (Dev Mode)</h3>
                    <div className="flex items-center justify-between bg-secondary p-3 rounded-lg">
                        <code className="text-xs text-muted-foreground font-mono truncate max-w-[200px]">{DEV_USER_ID}</code>
                        <button
                            onClick={() => navigator.clipboard.writeText(DEV_USER_ID)}
                            className="p-2 hover:text-primary transition-colors"
                        >
                            <Copy size={16} />
                        </button>
                    </div>
                </section>

                <section className="space-y-4">
                    <div>
                        <label className="text-sm font-medium">Units</label>
                        <div className="grid grid-cols-2 bg-secondary p-1 rounded-lg mt-1">
                            <button className="py-1.5 px-3 rounded-md bg-card shadow-sm text-sm font-medium">Lbs</button>
                            <button className="py-1.5 px-3 rounded-md text-muted-foreground text-sm font-medium hover:text-foreground">Kg</button>
                        </div>
                    </div>
                </section>
            </div>
        </PageLayout>
    );
}
