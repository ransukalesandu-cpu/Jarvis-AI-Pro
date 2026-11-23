import type { ReactNode } from 'react';
import { Button } from './Button';

export interface Column<T> {
    key: string;
    header: string;
    cell: (row: T) => ReactNode;
    align?: 'start' | 'end';
}

export interface TableProps<T> {
    caption: string;
    columns: Column<T>[];
    rows: T[];
    rowKey: (row: T) => string;
    loading?: boolean;
    error?: string;
    onRetry?: () => void;
    emptyText?: string;
}

/** Semantic table with loading (skeleton rows), error (with retry) and empty states. */
export function Table<T>({ caption, columns, rows, rowKey, loading, error, onRetry, emptyText = 'Nothing here yet.' }: TableProps<T>) {
    const span = columns.length;
    let body: ReactNode;
    if (error) {
        body = (
            <tr>
                <td colSpan={span} className="ui-table-state" role="alert">
                    <span className="ui-error">{error}</span>
                    {onRetry && (
                        <Button size="sm" variant="outline" tone="neutral" onClick={onRetry}>
                            Try again
                        </Button>
                    )}
                </td>
            </tr>
        );
    } else if (loading) {
        body = [0, 1, 2].map((i) => (
            <tr key={i} aria-hidden>
                {columns.map((c) => (
                    <td key={c.key}>
                        <span className="ui-skeleton" />
                    </td>
                ))}
            </tr>
        ));
    } else if (rows.length === 0) {
        body = (
            <tr>
                <td colSpan={span} className="ui-table-state">
                    {emptyText}
                </td>
            </tr>
        );
    } else {
        body = rows.map((r) => (
            <tr key={rowKey(r)}>
                {columns.map((c) => (
                    <td key={c.key} data-align={c.align}>
                        {c.cell(r)}
                    </td>
                ))}
            </tr>
        ));
    }
    return (
        <div className="ui-table-wrap" aria-busy={loading || undefined}>
            <table className="ui-table">
                <caption className="ui-sr-only">{caption}</caption>
                <thead>
                    <tr>
                        {columns.map((c) => (
                            <th key={c.key} scope="col" data-align={c.align}>
                                {c.header}
                            </th>
                        ))}
                    </tr>
                </thead>
                <tbody>{body}</tbody>
            </table>
        </div>
    );
}
