-- Demo for the `map` (combiner) feature.
-- Reads channels that the combiner injected and echoes a summary out.
-- The point of this file is to give the combiner something to feed; the maths
-- are deliberately trivial.

gn = input.getNumber
gb = input.getBool
sn = output.setNumber
sb = output.setBool

function onTick()
    -- ch17-19 come from source B, ch20 from source C (see combiner.mc)
    local x, y, z = gn(17), gn(18), gn(19)
    sn(1, math.sqrt(x * x + y * y + z * z))
    sn(2, gn(20))
    -- bool 5-7 were injected too
    sb(1, gb(5) and gb(6))
    sb(2, gb(7))
end
