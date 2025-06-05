const NO_GROUP_CATEGORY_NAME = "[No Group / Uncategorized]";

function parseM3UContentForWorker(content) {
    let localCategoriesData = {};
    let localOriginalHeader = "#EXTM3U";
    let localOtherDirectives = [];
    let tempCategories = {};

    const lines = content.split(/\r?\n/);
    let currentChannelInfo = null;

    if (lines.length > 0 && lines[0].trim().toUpperCase().startsWith("#EXTM3U")) {
        localOriginalHeader = lines[0].trim();
    }

    for (let i = 0; i < lines.length; i++) {
        const line = lines[i].trim();
        if (!line) continue;
        if (line.toUpperCase().startsWith("#EXTM3U")) continue;

        if (line.startsWith('#EXTINF:')) {
            currentChannelInfo = { info: line, name: '', attributes: {}, url: '' };

            // *** MODIFICATION START ***
            // Add a length check for the #EXTINF line before attempting regex for attributes
            // An #EXTINF line shouldn't typically be excessively long.
            // 4096 characters (4KB) is a generous limit; adjust if needed.
            if (line.length > 4096) {
                console.warn(`Skipping attribute parsing for extremely long #EXTINF line (length: ${line.length}). Line (first 200 chars): ${line.substring(0, 200)}...`);
                // Attributes for this currentChannelInfo will remain empty.
                // The name and URL parsing will still proceed below.
            } else {
                const attrRegex = /([a-zA-Z0-9_-]+)=("([^"]*)"|([^"\s]+))/g;
                let matchAttr;
                try {
                    while ((matchAttr = attrRegex.exec(line)) !== null) {
                        // Basic safeguard against prototype pollution, though less likely the cause of recursion here.
                        if (Object.prototype.hasOwnProperty.call(matchAttr, 1) &&
                            (matchAttr[1] === '__proto__' || matchAttr[1] === 'constructor' || matchAttr[1] === 'prototype')) {
                            console.warn(`Skipping potentially problematic attribute name: ${matchAttr[1]}`);
                            continue;
                        }
                        currentChannelInfo.attributes[matchAttr[1]] = matchAttr[3] || matchAttr[4];
                    }
                } catch (e_regex) {
                    // This catch might not trap "too much recursion" as it often unwinds the stack immediately,
                    // but it's good for other potential regex errors.
                    console.error(`Error during regex attribute parsing for line: ${line.substring(0,200)}...`, e_regex);
                }
            }
            // *** MODIFICATION END ***

            const nameMatch = line.match(/,(.+)$/);
            let displayName = nameMatch ? nameMatch[1].trim() : 'Unknown Channel';

            // --- REFINED HEURISTIC TO CLEANUP DISPLAY NAME --- (This part remains the same)
            if (displayName.length > 60 && displayName.includes('="')) {
                const markers = ['group-title="', 'tvg-logo="', 'tvg-name="', 'tvg-id="', 'catchup-source="'];
                let bestCandidateTitle = displayName;
                let lastAttributeEndPosition = -1;

                for (const marker of markers) {
                    let searchFrom = 0;
                    while (searchFrom < displayName.length) {
                        const markerPos = displayName.indexOf(marker, searchFrom);
                        if (markerPos === -1) break;

                        const quoteAfterMarker = displayName.indexOf('"', markerPos + marker.length);
                        if (quoteAfterMarker === -1) {
                            searchFrom = markerPos + marker.length;
                            continue;
                        }
                        if (quoteAfterMarker > lastAttributeEndPosition) {
                            lastAttributeEndPosition = quoteAfterMarker;
                        }
                        searchFrom = quoteAfterMarker + 1;
                    }
                }

                if (lastAttributeEndPosition !== -1) {
                    const commaAfterAttributes = displayName.indexOf(',', lastAttributeEndPosition + 1);
                    if (commaAfterAttributes !== -1) {
                        const potentialTitle = displayName.substring(commaAfterAttributes + 1).trim();
                        if (potentialTitle) {
                            let looksLikeMoreAttributes = false;
                            for (const marker of markers) {
                                if (potentialTitle.startsWith(marker) || (potentialTitle.includes('="') && potentialTitle.indexOf('="') < 20) ) {
                                    looksLikeMoreAttributes = true;
                                    break;
                                }
                            }
                            if (!looksLikeMoreAttributes) {
                                bestCandidateTitle = potentialTitle;
                            }
                        }
                    }
                }
                displayName = bestCandidateTitle;
            }
            currentChannelInfo.name = displayName;
            // --- END REFINED HEURISTIC ---

        } else if (currentChannelInfo && !line.startsWith('#')) {
            // ... (rest of this block remains the same) ...
            currentChannelInfo.url = line;
            const groupTitle = currentChannelInfo.attributes['group-title'] || NO_GROUP_CATEGORY_NAME;
            if (!tempCategories[groupTitle]) {
                tempCategories[groupTitle] = { state: true, channels: [], isExpanded: false };
            }
            tempCategories[groupTitle].channels.push({
                name: currentChannelInfo.name,
                info: currentChannelInfo.info,
                attributes: currentChannelInfo.attributes,
                url: currentChannelInfo.url,
                state: true
            });
            currentChannelInfo = null;
        } else if (currentChannelInfo && line.startsWith('#') && line.toUpperCase() !== "#EXTM3U") {
            // ... (rest of this block remains the same) ...
            const groupTitle = currentChannelInfo.attributes['group-title'] || NO_GROUP_CATEGORY_NAME;
            if (!tempCategories[groupTitle]) {
                tempCategories[groupTitle] = { state: true, channels: [], isExpanded: false };
            }
            tempCategories[groupTitle].channels.push({
                name: currentChannelInfo.name,
                info: currentChannelInfo.info,
                attributes: currentChannelInfo.attributes,
                url: '', // No URL if a directive follows EXTINF immediately
                state: true
            });
            currentChannelInfo = null; // Reset currentChannelInfo
            localOtherDirectives.push(line); // Store this directive
        } else if (line.startsWith('#')) {
            localOtherDirectives.push(line);
        }
    }

    // ... (Category sorting and rest of the function remain the same) ...
    const categoryKeys = Object.keys(tempCategories);
    const sortedCategoryNames = categoryKeys.sort((a, b) => {
        if (a === NO_GROUP_CATEGORY_NAME) return -1;
        if (b === NO_GROUP_CATEGORY_NAME) return 1;
        return a.toLowerCase().localeCompare(b.toLowerCase());
    });

    sortedCategoryNames.forEach(name => {
        tempCategories[name].channels.sort((a,b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
        localCategoriesData[name] = tempCategories[name];
    });

    return {
        categoriesData: localCategoriesData,
        originalHeader: localOriginalHeader,
        otherDirectives: localOtherDirectives
    };
}

// self.onmessage function remains the same, it calls parseM3UContentForWorker
self.onmessage = function(event) {
    const fileContent = event.data;
    try {
        const parsedData = parseM3UContentForWorker(fileContent); // This is line 140 from your error
        self.postMessage({ success: true, data: parsedData });
    } catch (error) {
        // A "too much recursion" error might not be catchable here if it's a fatal script error
        console.error("Worker: CAUGHT ERROR during parsing: ", error.message, error.stack);
        self.postMessage({ success: false, error: error.message + (error.stack ? `\nStack: ${error.stack}` : '') });
    }
};