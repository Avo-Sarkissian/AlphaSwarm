import { cn } from "@/lib/utils";

interface PageLayoutProps {
    children: React.ReactNode;
    className?: string;
    title?: string;
    action?: React.ReactNode;
}

export function PageLayout({ children, className, title, action }: PageLayoutProps) {
    return (
        <div className={cn("px-4 py-6 space-y-6 animate-in fade-in duration-300", className)}>
            {(title || action) && (
                <div className="flex items-center justify-between mb-2">
                    {title && <h1 className="text-2xl font-bold tracking-tight">{title}</h1>}
                    {action && <div>{action}</div>}
                </div>
            )}
            {children}
        </div>
    );
}
