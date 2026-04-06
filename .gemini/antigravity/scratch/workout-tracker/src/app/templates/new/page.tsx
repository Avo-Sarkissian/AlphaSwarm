'use client';

import Link from 'next/link';
import { Dumbbell, CalendarDays, ChevronLeft } from 'lucide-react';
import { PageLayout } from '@/components/ui/PageLayout';

export default function NewTemplatePage() {
    return (
        <PageLayout
            title="New Template"
            action={
                <Link href="/templates" className="p-2 -mr-2 text-muted-foreground hover:text-foreground">
                    <ChevronLeft size={24} />
                </Link>
            }
        >
            <div className="grid gap-4 mt-4">
                <Link
                    href="/templates/new/workout"
                    className="flex items-center gap-4 p-6 bg-card border border-border rounded-xl hover:border-primary transition-colors group"
                >
                    <div className="h-12 w-12 rounded-full bg-primary/10 text-primary flex items-center justify-center group-hover:scale-110 transition-transform">
                        <Dumbbell size={24} />
                    </div>
                    <div>
                        <h3 className="text-lg font-semibold text-foreground">Workout Template</h3>
                        <p className="text-sm text-muted-foreground">Single session (e.g., "Upper Body Power")</p>
                    </div>
                </Link>

                <Link
                    href="/templates/new/program"
                    className="flex items-center gap-4 p-6 bg-card border border-border rounded-xl hover:border-primary transition-colors group"
                >
                    <div className="h-12 w-12 rounded-full bg-secondary text-foreground flex items-center justify-center group-hover:scale-110 transition-transform">
                        <CalendarDays size={24} />
                    </div>
                    <div>
                        <h3 className="text-lg font-semibold text-foreground">Program Template</h3>
                        <p className="text-sm text-muted-foreground">Full week schedule with daily workouts</p>
                    </div>
                </Link>
            </div>
        </PageLayout>
    );
}
