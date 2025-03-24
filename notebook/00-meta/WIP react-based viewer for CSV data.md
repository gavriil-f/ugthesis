---
cssclasses:
  - table-100
---

```datacorejsx
return function CsvTableViewer() {
    const [csvPath, setCsvPath] = dc.useState("data/articles.csv");
    const [isLoaded, setIsLoaded] = dc.useState(false);
    const [error, setError] = dc.useState(null);
    const [csvData, setCsvData] = dc.useState({ columns: [], rows: [] });
    
    // Load CSV file when component mounts or path changes
    dc.useEffect(() => {
        const loadCsv = async () => {
            try {
                setIsLoaded(false);
                setError(null);
                
                // Try to get the file from the vault
                const file = app.vault.getAbstractFileByPath(csvPath);
                if (!file) {
                    setError(`File not found: ${csvPath}`);
                    return;
                }
                
                // Read file content
                const content = await app.vault.read(file);
                const lines = content.trim().split(/\r?\n/);
                
                if (lines.length === 0) {
                    setCsvData({ columns: [], rows: [] });
                    setIsLoaded(true);
                    return;
                }
                
                // Extract headers
                const headers = lines[0].split(',').map(header => header.trim());
                
                // Parse rows (limit to 50)
                const maxRows = Math.min(51, lines.length); // 50 data rows + header
                const rows = [];
                for (let i = 1; i < maxRows; i++) {
                    const values = lines[i].split(',').map(val => val.trim());
                    const row = {};
                    
                    headers.forEach((header, index) => {
                        row[header] = values[index] || '';
                    });
                    
                    rows.push(row);
                }
                
                setCsvData({ columns: headers, rows });
                setIsLoaded(true);
            } catch (err) {
                setError(`Failed to load CSV: ${err.message}`);
            }
        };
        
        loadCsv();
    }, [csvPath]);

    // Create table columns
    const columns = dc.useMemo(() => {
        if (!csvData.columns.length) return [];
        
        return csvData.columns.map(column => ({
            id: column,
            title: column,
            value: row => row[column]
        }));
    }, [csvData.columns]);
    
    // UI for setting CSV path
    const pathSelector = (
        <div style={{ marginBottom: "15px" }}>
            <input 
                type="text" 
                value={csvPath} 
                onChange={(e) => setCsvPath(e.target.value)}
                placeholder="Path to CSV file"
                style={{ width: "80%", marginRight: "10px" }}
            />
            <button onClick={() => setCsvPath(csvPath)}>Load</button>
        </div>
    );
    
    // Show error if there is one
    if (error) {
        return (
            <div>
                {pathSelector}
                <div style={{ color: "red" }}>{error}</div>
            </div>
        );
    }
    
    // Show loading state
    if (!isLoaded) {
        return (
            <div>
                {pathSelector}
                <p>Loading CSV data…</p>
            </div>
        );
    }
    
    // No data state
    if (!csvData.rows.length) {
        return (
            <div>
                {pathSelector}
                <p>No data found in the CSV file</p>
            </div>
        );
    }
    
    // Return the table with the CSV data
    return (
        <div>
            {pathSelector}
            <p>Showing first {csvData.rows.length} rows with {csvData.columns.length} columns</p>
            
            <dc.VanillaTable 
                columns={columns}
                rows={csvData.rows}
            />
        </div>
    );
}
```