import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatLabel, formatValue } from "@/lib/utils";

interface Props {
  columns: string[];
  rows: unknown[][];
}

export function ResultTable({ columns, rows }: Props) {
  return (
    <div className="max-h-80 overflow-auto rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            {columns.map((column) => (
              <TableHead key={column}>{formatLabel(column)}</TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, i) => (
            // eslint-disable-next-line react/no-array-index-key
            <TableRow key={i}>
              {row.map((value, j) => (
                <TableCell key={columns[j]}>{formatValue(value)}</TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
