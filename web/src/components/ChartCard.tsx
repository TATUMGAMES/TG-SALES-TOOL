/*
 * Copyright 2013-present Tatum Games, LLC.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at: https://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
 * WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 */

import { BarChart3, Download, Table2 } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { saveCsv } from "@/lib/csv";

/**
 * A chart with an accessible data-table alternative and CSV export of the same
 * numbers (the chart never shows anything the table does not).
 */
export function ChartCard({
  title,
  description,
  headers,
  rows,
  csvName,
  children,
  className,
}: {
  title: string;
  description?: ReactNode;
  headers: string[];
  rows: (string | number | null)[][];
  csvName: string;
  children: ReactNode;
  className?: string;
}) {
  const [table, setTable] = useState(false);
  return (
    <Card className={className}>
      <CardHeader
        title={title}
        description={description}
        actions={
          <>
            <Button variant="ghost" size="sm" onClick={() => setTable(!table)} aria-pressed={table}>
              {table ? <BarChart3 /> : <Table2 />} {table ? "Show chart" : "Show data table"}
            </Button>
            <Button variant="ghost" size="icon-sm" aria-label={`Export ${title} as CSV`} onClick={() => saveCsv(csvName, headers, rows)}>
              <Download />
            </Button>
          </>
        }
      />
      <div className="p-5 pt-3">
        {table ? (
          <div className="max-h-80 overflow-auto rounded-lg border">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-muted text-left text-xs uppercase text-muted-foreground">
                <tr>{headers.map((h) => <th key={h} className="px-3 py-2">{h}</th>)}</tr>
              </thead>
              <tbody>
                {rows.map((row, i) => (
                  <tr key={i} className="border-t">
                    {row.map((cell, j) => (
                      <td key={j} className={typeof cell === "number" ? "tabular px-3 py-1.5 text-right" : "px-3 py-1.5"}>
                        {cell === null ? "Not available" : typeof cell === "number" ? cell.toLocaleString() : cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div role="img" aria-label={`${title} chart. Use “Show data table” for the numbers.`}>
            {children}
          </div>
        )}
      </div>
    </Card>
  );
}
