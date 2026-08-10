import type { Track } from '../types'
import { journeyNameMatchesConvention } from '../brands'

// Steps are deliberately small. If a lesson needs more than about three short
// paragraphs, it gets split — a long screen is a failed screen here.
const track: Track = {
  id: 'crm-chile-v1',
  name: 'CRM Chile — Foundations',
  description: 'Player Journeys, the node types, and your first hands-on campaign.',

  steps: [
    // ── 0 · say hello before anything else ──────────────────────────────────
    {
      id: 'lesson-welcome',
      chapter: 'Welcome',
      type: 'lesson',
      eyebrow: 'Welcome',
      title: 'Welcome in. Here is the plan.',
      content: [
        {
          kind: 'paragraph',
          html: 'Hello, and welcome to the CRM team. This takes about half an hour, and <strong>nothing you do here touches anything real</strong>. Every screen is a safe copy, so click freely and get things wrong. That is what it is for.',
        },
        {
          kind: 'paragraph',
          html: 'The job you are learning is building <strong>promotions</strong>: the offers players see on the site, and the automations behind them that decide who gets what, and when.',
        },
        {
          kind: 'rule-list',
          rules: [
            {
              text: 'First, a real example.',
              sub: 'One of our own promos, the Fortune Wheel, followed from the player’s screen through to our logs, so you can see what you are aiming at before anyone explains a single term.',
            },
            {
              text: 'Then the building blocks.',
              sub: 'The node types, and the handful of rules that decide whether a journey works or quietly does nothing at all.',
            },
            {
              text: 'Then you build one yourself.',
              sub: 'Set a journey up, assemble the flow, and wire a promo page to it, on replicas of the screens you will use for real.',
            },
          ],
        },
        {
          kind: 'paragraph',
          html: 'Take it in order, and use Continue when you are ready.',
        },
      ],
    },

    // ── 1a · one real spin, paired onto as few screens as possible ───────────
    //
    // Captured 07.08.2026 from randomizer RND-0-17731 and journey JRN-0-572381.
    // Every capture is the same wheel and the same player, so the ids line up
    // across screens and a trainee can follow one story rather than samples.
    {
      id: 'lesson-spin-01',
      chapter: 'One real spin',
      tip: 'A journey never goes looking for players. The promo page delivers them.',
      type: 'lesson',
      eyebrow: 'One real spin · 1 of 6',
      title: 'It starts on the promo page.',
      content: [
        {
          kind: 'shots',
          items: [
            {
              src: 'shots/16.09.43.png',
              alt: 'The Bonificaciones list on the site, with a Casino card reading ¡Gira la Rueda de la Fortuna ahora! counting down 15H 48M.',
              caption: '16:09:43. The wheel is one card among the rest, with its own countdown.',
            },
            {
              src: 'shots/16.09.52.png',
              alt: 'The Rueda de la fortuna page: a twelve wedge wheel showing 50 GG con depósito, 50 GG sin depósito, Bonos de depósito and Jackpot 200 FS, with a Spin button.',
              caption: '16:09:52. Nine seconds later, on the wheel itself.',
            },
          ],
        },
        {
          kind: 'paragraph',
          html: 'Nothing runs until someone taps. At 16:09:43 our side has <strong>no record of this player at all</strong>. A journey never goes looking for anyone.',
        },
        {
          kind: 'paragraph',
          html: 'On the wheel, count the labels rather than the wedges. There are <strong>four</strong> prizes, each repeated three times around the rim so it looks full. The draw only ever sees four outcomes.',
        },
      ],
    },

    {
      id: 'lesson-spin-02',
      chapter: 'One real spin',
      tip: 'A prize is a probability and a destination journey. Nothing more.',
      type: 'lesson',
      eyebrow: 'One real spin · 2 of 6',
      title: 'The wheel decides, and we set the odds.',
      content: [
        {
          kind: 'shots',
          items: [
            {
              src: 'shots/16.10.13.png',
              alt: 'A Tu recompensa dialog over the wheel, confetti around a 50 GG CON DEPÓSITO badge, saying the bonus will activate automatically.',
              caption: '16:10:13. Tu recompensa. They drew 50 GG con depósito, the 55% slice.',
            },
            {
              src: 'shots/17.31.21.png',
              alt: 'The randomizer prize table for this wheel: four rows, each a JRN journey id against a probability of 55, 42, 2.7 and 0.3, above a greyed out Add prize button, with the promo link casino-wof-07-08-2026.',
              caption: 'The prize table for this exact wheel. Four journeys, four probabilities, totalling 100.',
            },
          ],
        },
        {
          kind: 'paragraph',
          html: 'The player did not choose that prize and neither did we, on the day. The wheel did.',
        },
        {
          kind: 'paragraph',
          html: 'But the odds are ours. Someone typed them, and they must total 100. <em>Add prize</em> is greyed out because the slices come from the captured template, so you set the weights, never the count. A slice left at 0% stays on the wheel and never lands.',
        },
        {
          kind: 'paragraph',
          html: 'Now look at what a prize actually <em>is</em>. Every row is a <strong>JRN, a journey id</strong>. Winning a slice does one single thing: it <strong>adds the player into that journey</strong>. Nothing is awarded by the wheel itself.',
        },
        {
          kind: 'paragraph',
          html: 'So everything that happens next lives inside that journey: the offer, the deposit gate, the free spins, the wagering bonus, and an exit for every player who does not finish. The 55% row, <strong>JRN-0-572381</strong>, is the one this player drew. Which fixes the build order: <strong>the journeys exist first</strong>, because this table can only point at journeys that are already there.',
        },
      ],
    },

    {
      id: 'lesson-spin-03',
      chapter: 'One real spin',
      tip: 'Naming is how you find one object among thousands.',
      type: 'lesson',
      eyebrow: 'One real spin · 3 of 6',
      title: 'Where that lives on our side.',
      content: [
        {
          kind: 'shots',
          items: [
            {
              src: 'shots/16.10.45.png',
              alt: 'The backoffice Promo list filtered to Active, showing randomizer RND-0-17731 JBCL|CS|WOF|07.08.26 with an open row menu offering Duplicate, View player list, Export players and Terminate.',
              caption: '16:10:45. The same wheel in the Promo list, as an object you can find.',
            },
          ],
        },
        {
          kind: 'paragraph',
          html: 'One row, one wheel: <strong>RND-0-17731</strong>, mechanics <em>Randomizer / Fortune wheel</em>, brand <code>.jbcl</code>, live 07.08 08:02 until 08.08 07:58. The row menu is where you go to see who played it.',
        },
      ],
    },

    {
      id: 'lesson-spin-04',
      chapter: 'One real spin',
      tip: 'A chooser asks. It awards nothing on its own.',
      type: 'lesson',
      eyebrow: 'One real spin · 4 of 6',
      title: 'Now the player chooses.',
      content: [
        {
          kind: 'shots',
          items: [
            {
              src: 'shots/16.12.04.png',
              alt: 'A promotion screen titled 50 GG CON DEPÓSITO DE LA RUEDA DE LA FORTUNA, ID 672079, with a notice reading Selecciona 1 de los 3 bonos and three options at $200, $100 and $1,000 bet, each with Seleccionar and Detalles buttons.',
              caption: '16:12:04. Selecciona 1 de los 3 bonos. Three bets: $200, $100, $1,000.',
            },
            {
              src: 'shots/17.30.42.png',
              alt: 'The same offer on the journey canvas: Accepted 17678 branching into Flow 1, Flow 2 and Flow 3, labelled 15k dep, 10k dep and big, each running its own deposit gate, Casino FreeSpin and Casino bonus with player counts on every path.',
              caption: 'The same offer on our canvas. Three flows, one per option, each complete on its own.',
            },
          ],
        },
        {
          kind: 'paragraph',
          html: 'This is the most useful screen in the course. It is what a <strong>Multipurpose Promotion</strong> looks like from the outside: it awards nothing, it <em>asks</em>. The player picks one of three flows and only that one runs.',
        },
        {
          kind: 'paragraph',
          html: 'On our canvas those three options are <strong>three flows</strong>, named 15k dep, 10k dep and big. Each one is complete on its own: its own offer, deposit gate, free spins and bonus. A player runs exactly one of them, the one they picked, and the counts on each path show how the 17 678 who accepted split across them.',
        },
        {
          kind: 'paragraph',
          html: 'It also explains a gap in the log. The offer went up at 16:10 and was accepted at 16:12, nearly two minutes, because a person was reading three options. Every other step took about a second.',
        },
      ],
    },

    {
      id: 'lesson-spin-05',
      chapter: 'One real spin',
      tip: 'The terms belong to the option the player picked.',
      type: 'lesson',
      eyebrow: 'One real spin · 5 of 6',
      title: 'One bonus, with its own terms.',
      content: [
        {
          kind: 'shots',
          items: [
            {
              src: 'shots/16.12.20.png',
              alt: 'The Bonificaciones page showing ACTIVA · 1 and a single card, 50 Giros Gratis | Apuesta $200, with 15000 CLP minimum deposit, a Depósito button and 23H 59M remaining.',
              caption: '16:12:20. They chose the $200 bet. It is now their one active bonus.',
            },
          ],
        },
        {
          kind: 'paragraph',
          html: 'The chosen flow brought its own offer with it: <strong>15.000 CLP minimum deposit</strong>. In the log that node is called “15k dep”. The terms belong to the option, not to the chooser.',
        },
        {
          kind: 'paragraph',
          html: 'A <strong>second</strong> clock also started. One day to accept the offer, a separate day to deposit now they have. A player can beat the first and still miss the second.',
        },
      ],
    },

    {
      id: 'lesson-spin-06',
      chapter: 'One real spin',
      tip: 'Every prize needs its journey built first.',
      type: 'lesson',
      eyebrow: 'One real spin · 6 of 6',
      title: 'Who spun, and what happened next.',
      content: [
        {
          kind: 'shots',
          items: [
            {
              src: 'shots/16.13.34.png',
              alt: 'The randomizer players list for RND-0-17731 showing one account, added 16:09, activated 16:09, claimed 16:10, with bonus campaign JRN-0-572381 described as Wheel of fortune | 50FS to dep.',
              caption: '16:13:34. Who spun, and the journey the prize routed into.',
            },
            {
              src: 'shots/16.13.54.png',
              alt: 'The Journey log for one player: deposit activated 08:12:11, 15k dep promotion accepted 08:12:10 in Flow 1, Multipurpose Promotion accepted then offered, a decision split, and API player added to journey 08:10:07.',
              caption: '16:13:54. That player’s whole journey. Newest first, so read upward.',
            },
          ],
        },
        {
          kind: 'paragraph',
          html: 'A prize slice is not a prize. It is a weight plus a journey id, which is why <strong>every prize needs its journey built first</strong>. A wheel can only point at journeys that already exist.',
        },
        {
          kind: 'paragraph',
          html: 'The log on the right is what you open when someone says “I did not get my bonus”. Read upward: added by API, routed by a split, offered, accepted, the real offer accepted inside <strong>Flow 1</strong>, and the deposit gate armed one second later.',
        },
      ],
    },

    // ── 1b · what that log settles ───────────────────────────────────────────
    {
      id: 'lesson-spin-rules',
      chapter: 'One real spin',
      tip: 'Give every flow its own promotion inside it.',
      type: 'lesson',
      eyebrow: 'One real spin · what it proves',
      title: 'Three things that log settles.',
      content: [
        {
          kind: 'rule-list',
          rules: [
            {
              text: 'Two promotions accepted, one second apart.',
              sub: 'The Multipurpose Promotion is the chooser. It records which flow was picked and awards nothing. “15k dep” is the real offer inside that flow, and the deposit gate hangs off it. A reward needs that inner promotion; behind the chooser alone it has no offer to belong to.',
            },
            {
              text: 'One node can fire twice.',
              sub: 'Offered and Accepted share the same activity id. Choosing a flow adds nodes. It never re-uses the chooser.',
            },
            {
              text: 'A promotion node awards nothing on its own.',
              sub: 'It is the surface a player opts in on. The condition and reward nodes behind it are the journey. A flow that stops at the promotion is a button wired to nothing.',
            },
          ],
        },
        {
          kind: 'paragraph',
          html: 'That is one promo, both sides, start to finish. Now the parts it was built from.',
        },
      ],
    },

    // ── 1 ───────────────────────────────────────────────────────────────────
    {
      id: 'lesson-what-is',
      chapter: 'Foundations',
      type: 'lesson',
      eyebrow: 'The idea',
      title: 'Player Journeys is a decision engine.',
      content: [
        {
          kind: 'paragraph',
          html: 'A <strong>journey</strong> watches what players do and answers on its own — no operator presses anything. It listens for an action, applies your logic, and hands out a reward or a message.',
        },
        {
          kind: 'diagram',
          boxes: [
            {
              id: 'event',
              label: 'Player action',
              examples: ['Registers', 'Makes a deposit', 'Goes quiet for 14 days'],
            },
            {
              id: 'journey',
              label: 'Journey',
              examples: ['Waits', 'Conditions', 'Branches'],
            },
            {
              id: 'action',
              label: 'Response',
              examples: ['Free spins', 'Deposit bonus', 'Notification'],
            },
          ],
          arrows: [
            { from: 'event', to: 'journey' },
            { from: 'journey', to: 'action' },
          ],
        },
      ],
    },

    // ── 2 ───────────────────────────────────────────────────────────────────
    {
      id: 'lesson-timeline',
      chapter: 'Foundations',
      type: 'lesson',
      eyebrow: 'How it runs',
      title: 'Every player runs on their own clock.',
      content: [
        {
          kind: 'paragraph',
          html: 'Once published, a journey runs continuously. Each qualifying player enters at the top and moves along their own timeline, independent of everyone else.',
        },
        {
          kind: 'paragraph',
          html: 'So a one-hour wait means one hour <em>after that player arrived</em> — not one hour after you hit publish. Two players who enter a day apart are simply at different points of the same journey.',
        },
      ],
    },

    // ── 3 ───────────────────────────────────────────────────────────────────
    {
      id: 'lesson-where',
      chapter: 'Foundations',
      type: 'lesson',
      eyebrow: 'Where it lives',
      title: 'Journey builder is the list of everything running.',
      content: [
        {
          kind: 'paragraph',
          html: 'Every journey the team has ever built sits here — running, planned, terminated. You will spend most of your time on this screen.',
        },
        {
          kind: 'screen',
          name: 'journeys-list',
          caption:
            'Note the names. The brand code opens every one, so the list can be scanned by brand without opening anything.',
        },
      ],
    },

    // ── 4 ───────────────────────────────────────────────────────────────────
    {
      id: 'lesson-promo',
      chapter: 'Foundations',
      type: 'lesson',
      eyebrow: 'What we create',
      title: 'Three things. Not nine.',
      content: [
        {
          kind: 'paragraph',
          html: 'The Promo section offers nine mechanics. In Chile we use two of them — <strong>Promo Page</strong> and <strong>Prediction</strong> — plus the <strong>Journey builder</strong> behind both. Ignore the rest until someone asks for it.',
        },
        {
          kind: 'screen',
          name: 'promo-list',
          caption: 'The two we create are marked. Everything else on that menu is someone else’s market.',
        },
      ],
    },

    // ── 5 ───────────────────────────────────────────────────────────────────
    {
      id: 'lesson-nodes',
      chapter: 'The blocks',
      type: 'lesson',
      eyebrow: 'The blocks',
      title: 'Six blocks. The whole language.',
      content: [
        {
          kind: 'paragraph',
          html: 'Every journey — simple or elaborate — is assembled from the same six node types. Learn these and you can read any journey on the canvas.',
        },
        {
          kind: 'table',
          rows: [
            { node: 'Entry Source', role: 'Decides who enters the journey' },
            { node: 'Wait', role: 'Holds the player until the right moment' },
            { node: 'Condition', role: 'Asks whether the player did the thing' },
            { node: 'Reward', role: 'Credits a bonus automatically' },
            { node: 'Communication', role: 'Sends a message on one channel' },
            { node: 'Exit', role: 'Ends that player’s journey' },
          ],
        },
      ],
    },

    // ── 4 ───────────────────────────────────────────────────────────────────
    {
      id: 'lesson-rules-shape',
      chapter: 'The rules',
      type: 'lesson',
      eyebrow: 'Rules — shape',
      title: 'Three rules about shape.',
      content: [
        {
          kind: 'paragraph',
          html: 'These are not preferences. A journey that breaks one of them fails to save, or runs quietly wrong.',
        },
        {
          kind: 'rule-list',
          rules: [
            {
              text: 'Every journey starts with exactly one Entry Source.',
              sub: 'It is the door a Promo Page points at. You cannot have two, and you cannot swap it after launch without updating the page.',
            },
            {
              text: 'Every node must connect to the next one.',
              sub: 'There is no implicit “carry on”. An unconnected node is a dead end, and the player stops there.',
            },
            {
              text: 'Every path must end in an Exit.',
              sub: 'Including the path for players who did not qualify. Without one they stay active in the journey and count in its audience forever.',
            },
          ],
        },
      ],
    },

    // ── 5 ───────────────────────────────────────────────────────────────────
    {
      id: 'lesson-rules-behaviour',
      chapter: 'The rules',
      type: 'lesson',
      eyebrow: 'Rules — behaviour',
      title: 'Three rules about behaviour.',
      content: [
        {
          kind: 'rule-list',
          rules: [
            {
              text: 'Waits pause. They do not branch.',
              sub: 'A Wait has one way forward: the clock runs out. It decides nothing.',
            },
            {
              text: 'Conditions branch — connect every outcome.',
              sub: 'A Deposit Condition has three: deposited, did not deposit, offer expired. All three need somewhere to go, even if two go straight to an Exit.',
            },
            {
              text: 'Save your change in both places.',
              sub: 'A journey lives twice — the visual canvas and the settings behind it. An edit saved to only one of them ships the wrong content with no warning.',
            },
          ],
        },
      ],
    },

    // ── 6 ───────────────────────────────────────────────────────────────────
    {
      id: 'lesson-promo-vs-journey',
      chapter: 'Distinctions',
      type: 'lesson',
      eyebrow: 'A distinction',
      title: 'A promotion is not a journey.',
      content: [
        {
          kind: 'paragraph',
          html: 'This is the most common mix-up. A <strong>promotion</strong> is what the player receives. A <strong>journey</strong> is what decides whether they receive it, when, and on what terms.',
        },
        {
          kind: 'split-card',
          left: {
            heading: 'Promotion',
            title: '50 Free Spins',
            body: 'What the player gets. Configured in the Promotions section, with its own name, display rules and reward details. The journey points at it — it does not contain it.',
          },
          right: {
            heading: 'Journey',
            title: 'First Deposit Flow',
            body: 'How the player gets it. Register → wait 1h → check deposit → grant spins → notify. The reward node inside references the promotion by name.',
          },
        },
        {
          kind: 'paragraph',
          html: 'The same promotion can be used by several journeys. Updating its details never means touching them.',
        },
      ],
    },

    // ── 6b ──────────────────────────────────────────────────────────────────
    {
      id: 'lesson-connection',
      chapter: 'Distinctions',
      type: 'lesson',
      eyebrow: 'The wiring',
      title: 'One field connects the two.',
      content: [
        {
          kind: 'paragraph',
          html: 'Building a promo page ends on this screen. Brand, currency, the URLs the player will land on — and then <strong>Journey Builder connection</strong>, where you pick the Journey ID.',
        },
        {
          kind: 'screen',
          name: 'promo-page-form',
          caption:
            'That dropdown is the whole link between a promotion and its automation. Pick the wrong journey here and the page pays out somebody else’s campaign.',
        },
        {
          kind: 'paragraph',
          html: 'Which is why the journey is named <strong>JBCL | CS | RB - Game of the week | 50 FS</strong> and not “test 3”. You are choosing it from a list of eighteen hundred.',
        },
      ],
    },

    // ── 6c ──────────────────────────────────────────────────────────────────
    {
      id: 'lesson-player-side',
      chapter: 'Distinctions',
      type: 'lesson',
      eyebrow: 'The player’s side',
      title: 'The button is the door.',
      content: [
        {
          kind: 'paragraph',
          html: 'Everything you connect shows up under <strong>Promociones</strong> on the site. Each card here is a promo page you built.',
        },
        {
          kind: 'screen',
          name: 'promotions-site',
          caption:
            'Juega Ahora, Participate — whatever the button says, pressing it is the moment the player enters the journey you attached.',
        },
        {
          kind: 'paragraph',
          html: 'So nothing runs until someone taps. The journey does not go looking for players; the promo page delivers them, one press at a time, each starting their own clock.',
        },
      ],
    },

    // ── 7 ───────────────────────────────────────────────────────────────────
    {
      id: 'showcase-gotw',
      chapter: 'A real campaign',
      type: 'showcase',
      eyebrow: 'One real campaign',
      title: 'Game of the Week, set up.',
      description:
        'One campaign, built from the three things you just met. Open any step to see what we actually create.',
      items: [
        {
          id: 'sc-page',
          label: 'Promo Page — the thing the player opens',
          description:
            'Created from Promo → Create new → Promo Page. It carries the match artwork, the terms, and the button. It is also the door: opening it is what puts a player into the journey.',
        },
        {
          id: 'sc-prediction',
          label: 'Prediction — the mechanic, when the match needs one',
          description:
            'Created from Promo → Create new → Prediction. Game of the Week can run without it, but when we ask players to call a scoreline this is the object that collects and settles the answers.',
        },
        {
          id: 'sc-journey',
          label: 'Journey builder — the automation behind both',
          description:
            'Created from Journey builder → Create new, named JBCL | Game of the Week 06.08. The promo objects are what the player sees; the journey is what decides and pays.',
        },
        {
          id: 'sc-source',
          label: 'Entry Source — from the Promo Page',
          description:
            'Players enter when they open the match Promo Page. The source registers them and starts their personal clock.',
        },
        {
          id: 'sc-cond',
          label: 'Deposit Condition — $10,000 CLP minimum, 48h window',
          description:
            'The journey checks for a deposit of at least $10,000 CLP within 48 hours of entry. Deposited goes to the reward; did not goes to an exit.',
        },
        {
          id: 'sc-reward',
          label: 'Reward — 20% deposit match, capped at $50,000 CLP',
          description:
            'Credited automatically; the player claims nothing. Amount, cap and wagering requirement are all set inside the node.',
        },
        {
          id: 'sc-comms',
          label: 'Communication — “Your bonus is ready”',
          description:
            'Sent once the bonus is credited. It references a Content Studio template and lands in the player’s notification bell.',
        },
        {
          id: 'sc-exit',
          label: 'Exit — on both paths',
          description:
            'Two exits: one after the notification, one straight off the condition for players who never deposited. Both have to exist.',
        },
      ],
    },

    // ── 8 ───────────────────────────────────────────────────────────────────
    {
      id: 'task-journey-settings',
      chapter: 'Build it',
      type: 'task',
      eyebrow: 'Your turn',
      title: 'Set the journey up.',
      brief:
        'A welcome journey for Chile casino players. It should start the moment it is published, and stop accepting new players on 07.08. Work in any order — the checks tell you where you are.',

      replica: {
        id: 'journey-settings-replica',
        screen: 'journey-settings',
        screenTitle: 'New Journey',
        screenSubtitle: 'General settings',
      },

      checks: [
        {
          id: 'c-brand',
          label: 'Brand is JBCL',
          test: ctx => ctx.fields.brand === 'JBCL',
        },
        {
          id: 'c-name',
          label: 'Title follows the naming convention',
          test: ctx =>
            journeyNameMatchesConvention(ctx.fields['journey-title'] ?? '', ctx.fields.brand),
        },
        {
          id: 'c-start',
          label: 'Starts immediately after publish',
          test: ctx => ctx.fields['start-immediately'] === 'true',
        },
        {
          id: 'c-entry',
          label: 'Entry closes on 07.08',
          test: ctx => ctx.fields['entry-until'] === '2026-08-07',
        },
        {
          id: 'c-product',
          label: 'Product type is Casino',
          test: ctx => ctx.fields['product-type'] === 'casino',
        },
        {
          id: 'c-purpose',
          label: 'Purpose is Marketing - Welcome',
          test: ctx => ctx.fields.purpose === 'marketing-welcome',
        },
      ],
    },

    // ── 9 ───────────────────────────────────────────────────────────────────
    {
      id: 'task-journey-builder',
      chapter: 'Build it',
      type: 'task',
      eyebrow: 'Your turn',
      title: 'Build the flow.',
      brief:
        'Now assemble it. Players come in from a segment, we wait, we check they deposited, we pay a casino reward, and we tell them. Drag activities from the palette onto the canvas — drop between two nodes to insert, drag a node to reorder, and click one to add it without dragging.',

      replica: {
        id: 'journey-builder-replica',
        screen: 'journey-builder',
        screenTitle: 'Journey builder',
      },

      checks: [
        {
          id: 'b-source',
          label: 'Starts with an input source',
          test: ctx => ctx.canvas[0] === 'act-custom-segment',
        },
        {
          id: 'b-wait',
          label: 'Has a Wait',
          test: ctx => ctx.canvas.includes('act-wait'),
        },
        {
          id: 'b-deposit',
          label: 'Has a Deposit condition',
          test: ctx => ctx.canvas.includes('act-deposit'),
        },
        {
          id: 'b-reward',
          label: 'Pays a casino reward',
          test: ctx =>
            ctx.canvas.includes('act-casino-freespin') || ctx.canvas.includes('act-casino-bonus'),
        },
        {
          id: 'b-comms',
          label: 'Tells the player something',
          test: ctx =>
            ['act-email', 'act-sms', 'act-native-push', 'act-onsite-messaging'].some(id =>
              ctx.canvas.includes(id),
            ),
        },
        {
          id: 'b-order',
          label: 'Condition comes before the reward',
          test: ctx => {
            const cond = ctx.canvas.indexOf('act-deposit')
            const reward = Math.max(
              ctx.canvas.indexOf('act-casino-freespin'),
              ctx.canvas.indexOf('act-casino-bonus'),
            )
            return cond !== -1 && reward !== -1 && cond < reward
          },
        },
      ],
    },

    // ── 10 ──────────────────────────────────────────────────────────────────
    {
      id: 'task-gotw',
      chapter: 'Build it',
      type: 'task',
      eyebrow: 'Your turn',
      title: 'Fill the campaign.',
      brief:
        'Game of the Week for Colo-Colo vs Concepción this weekend: a 20% deposit match, connected to the standard GotW journey. Save it as a draft when the form is right.',

      replica: {
        id: 'gotw-replica',
        screenTitle: 'New Campaign',
        screenSubtitle: 'Game of the Week',
        panels: [
          { id: 'campaign-details', title: 'Campaign details' },
          { id: 'featured-event', title: 'Featured event' },
          { id: 'reward-config', title: 'Reward' },
          { id: 'journey-link', title: 'Journey' },
        ],
        elements: [
          {
            id: 'campaign-name',
            type: 'input',
            panel: 'campaign-details',
            label: 'Campaign name',
            placeholder: 'e.g. GotW — Colo-Colo vs Concepción',
          },
          {
            id: 'campaign-type',
            type: 'select',
            panel: 'campaign-details',
            label: 'Campaign type',
            defaultValue: '',
            options: [
              { value: '', label: 'Select type…' },
              { value: 'welcome', label: 'Welcome' },
              { value: 'gotw', label: 'Game of the Week' },
              { value: 'reactivation', label: 'Reactivation' },
              { value: 'vip', label: 'VIP upgrade' },
            ],
          },
          {
            id: 'active-from',
            type: 'input',
            panel: 'campaign-details',
            label: 'Active from',
            defaultValue: '2026-08-07',
            readonly: true,
          },
          {
            id: 'active-to',
            type: 'input',
            panel: 'campaign-details',
            label: 'Active to',
            defaultValue: '2026-08-08',
            readonly: true,
          },

          {
            id: 'sport',
            type: 'select',
            panel: 'featured-event',
            label: 'Sport',
            defaultValue: '',
            options: [
              { value: '', label: 'Select sport…' },
              { value: 'football', label: 'Football' },
              { value: 'tennis', label: 'Tennis' },
              { value: 'basketball', label: 'Basketball' },
            ],
          },
          {
            id: 'match',
            type: 'select',
            panel: 'featured-event',
            label: 'Match',
            defaultValue: '',
            options: [
              { value: '', label: 'Select match…' },
              { value: 'colo-concep', label: 'Colo-Colo vs Concepción' },
              { value: 'uc-huachipato', label: 'U. Católica vs Huachipato' },
              { value: 'liverpool-chelsea', label: 'Liverpool vs Chelsea' },
            ],
          },

          {
            id: 'bonus-type',
            type: 'select',
            panel: 'reward-config',
            label: 'Bonus type',
            defaultValue: '',
            options: [
              { value: '', label: 'Select bonus type…' },
              { value: 'freespins', label: 'Free spins' },
              { value: 'deposit-match', label: 'Deposit match (%)' },
              { value: 'freebet', label: 'Free bet' },
            ],
          },
          {
            id: 'bonus-pct',
            type: 'input',
            panel: 'reward-config',
            label: 'Bonus percentage (%)',
            placeholder: 'e.g. 20',
          },
          {
            id: 'min-deposit',
            type: 'input',
            panel: 'reward-config',
            label: 'Minimum deposit (CLP)',
            placeholder: 'e.g. 10000',
          },
          {
            id: 'max-bonus',
            type: 'input',
            panel: 'reward-config',
            label: 'Maximum bonus (CLP)',
            placeholder: 'e.g. 50000',
          },

          {
            id: 'journey-select',
            type: 'select',
            panel: 'journey-link',
            label: 'Journey to connect',
            defaultValue: '',
            options: [
              { value: '', label: 'Select journey…' },
              { value: 'first-deposit', label: 'First Deposit Flow' },
              { value: 'gotw-standard', label: 'GotW — standard deposit' },
              { value: 'reactivation', label: 'Reactivation 14 days' },
            ],
          },

          { id: 'btn-save', type: 'button', label: 'Save draft', variant: 'secondary' },
          { id: 'btn-publish', type: 'button', label: 'Publish campaign', variant: 'primary' },
        ],
      },

      checks: [
        {
          id: 'g-name',
          label: 'Campaign is named',
          test: ctx => (ctx.fields['campaign-name'] ?? '').trim().length > 3,
        },
        {
          id: 'g-type',
          label: 'Type is Game of the Week',
          test: ctx => ctx.fields['campaign-type'] === 'gotw',
        },
        {
          id: 'g-match',
          label: 'Colo-Colo vs Concepción is the featured match',
          test: ctx => ctx.fields.sport === 'football' && ctx.fields.match === 'colo-concep',
        },
        {
          id: 'g-bonus',
          label: 'A 20% deposit match',
          test: ctx =>
            ctx.fields['bonus-type'] === 'deposit-match' &&
            (ctx.fields['bonus-pct'] ?? '').trim() === '20',
        },
        {
          id: 'g-journey',
          label: 'Connected to the GotW journey',
          test: ctx => ctx.fields['journey-select'] === 'gotw-standard',
        },
        {
          id: 'g-saved',
          label: 'Saved as a draft',
          test: ctx => ctx.fields['btn-save'] === 'pressed',
        },
      ],
    },
  ],
}

export default track
