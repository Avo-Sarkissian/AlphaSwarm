'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Dumbbell, LineChart, Files, Settings } from 'lucide-react';
import { cn } from '@/lib/utils';

const NAV_ITEMS = [
    { label: 'Train', href: '/train', icon: Dumbbell },
    { label: 'Progress', href: '/progress', icon: LineChart },
    { label: 'Templates', href: '/templates', icon: Files },
    { label: 'Settings', href: '/settings', icon: Settings },
];

export function BottomNav() {
    const pathname = usePathname();

    return (
        <nav className="fixed bottom-0 left-0 right-0 z-50 border-t border-border bg-card/90 backdrop-blur-md pb-safe">
            <div className="flex items-center justify-around h-16 max-w-md mx-auto px-2">
                {NAV_ITEMS.map((item) => {
                    const isActive = pathname.startsWith(item.href);
                    const Icon = item.icon;

                    return (
                        <Link
                            key={item.href}
                            href={item.href}
                            className={cn(
                                "flex flex-col items-center justify-center w-full h-full space-y-1",
                                isActive ? "text-primary" : "text-muted-foreground hover:text-foreground transition-colors"
                            )}
                        >
                            <Icon size={24} strokeWidth={isActive ? 2.5 : 2} />
                            <span className="text-[10px] font-medium">{item.label}</span>
                        </Link>
                    );
                })}
            </div>
        </nav>
    );
}
