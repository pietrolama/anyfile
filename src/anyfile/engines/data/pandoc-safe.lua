-- ANYFILE's Pandoc filter: a converted document embeds only images that sit in the
-- original's folder (or are already inside it, like the media of a DOCX). Remote images
-- and paths that leave the folder become their description, so a crafted document can
-- neither pull another file of yours into the result nor make Pandoc reach the network.
-- In EPUB, raw HTML is dropped too, since the EPUB writer also embeds what it points to.

local function is_safe(src)
  if src:match("^data:") then
    return true
  end
  if src:match("^%a[%w+.-]*:") or src:match("^//") then
    return false -- a URL (http:, file:, ...)
  end
  if src:match("^/") or src:match("^\\") or src:match("^%a:[/\\]") or src:match("^~") then
    return false -- an absolute path
  end
  for part in src:gmatch("[^/\\]+") do
    if part == ".." then
      return false
    end
  end
  return true
end

function Image(img)
  if is_safe(img.src) then
    return nil
  end
  return pandoc.Span(img.caption)
end

local function drop_raw_html(raw)
  if FORMAT:match("epub") and raw.format:match("html") then
    return {}
  end
  return nil
end

RawInline = drop_raw_html
RawBlock = drop_raw_html
